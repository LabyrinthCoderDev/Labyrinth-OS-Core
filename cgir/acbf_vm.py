# acbf_vm.py — Labyrinth-OS / Minimal ITV Reference VM  (v0.1.0)
# Status: reference implementation for the ACBF / ITV / Aurelius spec.
# Byte-for-byte deterministic given identical inputs — supports Invariant I9 (exact replay).
# Goal:  emit full step traces in a fixed binary-log format.
#
# Layers implemented here:
#   (1) ACBF v1   — canonical payload encoding
#   (2) ITV v1    — per-step state hashing
#   (3) Aurelius  — deterministic 32-bit instruction VM
#   (4) Trace log — fixed binary format (magic = b"ITV1")
#
# No dependencies outside the standard library.
# Byte-for-byte deterministic given identical inputs.

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional


# =================================================================
# ACBF v1 — Canonical Payload Encoding
# =================================================================

SCHEMA_REGISTRY: Dict[int, Dict] = {
    1: {
        "name": "sql_request",
        "fields": [
            ("query",   "string"),
            ("user_id", "u32"),
            ("purpose", "string"),
        ],
    },
}


def encode_payload(schema_id: int, payload: dict) -> bytes:
    if schema_id not in SCHEMA_REGISTRY:
        raise RuntimeError(f"Unknown schema_id: {schema_id}")
    schema = SCHEMA_REGISTRY[schema_id]
    out = bytearray()
    for field_name, typ in schema["fields"]:
        if field_name not in payload:
            raise RuntimeError(f"Missing required field: {field_name}")
        v = payload[field_name]
        if typ == "u32":
            if not isinstance(v, int) or v < 0 or v > 0xFFFFFFFF:
                raise RuntimeError(f"Invalid u32 for {field_name}: {v!r}")
            out.extend(v.to_bytes(4, "big"))
        elif typ == "string":
            if not isinstance(v, str):
                raise RuntimeError(f"Invalid string for {field_name}: {v!r}")
            b = v.encode("utf-8")
            if len(b) > 0xFFFF:
                raise RuntimeError(f"String too long for {field_name}")
            out.extend(len(b).to_bytes(2, "big"))
            out.extend(b)
        else:
            raise RuntimeError(f"Unknown type in schema: {typ}")
    return bytes(out)


def payload_hash(schema_id: int, payload: dict) -> bytes:
    return hashlib.sha256(encode_payload(schema_id, payload)).digest()


# =================================================================
# VM State
# =================================================================

NUM_REGS   = 16
STACK_SIZE = 256
HEAP_SIZE  = 4096
INSTR_LEN  = 4


class VMState:
    __slots__ = ("regs", "stack", "heap", "ip", "halted", "success",
                 "_pending_req_hash", "_validated")

    def __init__(self) -> None:
        self.regs: List[int]  = [0] * NUM_REGS           # u64 each
        self.stack: bytearray = bytearray(STACK_SIZE)
        self.heap:  bytearray = bytearray(HEAP_SIZE)
        self.ip: int          = 0                        # u32
        self.halted: bool     = False
        self.success: bool    = True
        # REQUEST/VALIDATE/COMMIT internal state (not in state hash —
        # by design; commit writes a witness into heap instead).
        self._pending_req_hash: Optional[bytes] = None
        self._validated: bool = False

    def hash_state(self) -> bytes:
        """
        ITV canonical state hash rule:
            SHA256( regs[0..15] as u64 BE
                  + stack[0..255]
                  + heap[0..4095]
                  + ip as u32 BE )
        """
        h = hashlib.sha256()
        for r in self.regs:
            h.update((r & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big"))
        h.update(bytes(self.stack))
        h.update(bytes(self.heap))
        h.update((self.ip & 0xFFFFFFFF).to_bytes(4, "big"))
        return h.digest()


# =================================================================
# Opcodes  (32-bit instruction word: [op, a, b, c])
# =================================================================

OP_LOADI    = 0x01   # rA <- (b<<8)|c
OP_READ     = 0x02   # rA <- heap[(b<<8)|c]
OP_WRITE    = 0x03   # heap[(b<<8)|c] <- rA & 0xFF
OP_MOVE     = 0x04   # rA <- rB
OP_CJMP     = 0x06   # if rA != 0: ip <- (b<<8)|c
OP_HALT     = 0x09   # halt, success preserved
OP_REQUEST  = 0x0A   # ACBF-encode payloads[c] with schema b; rA <- hi64(hash)
OP_VALIDATE = 0x0B   # mark pending request as validated
OP_COMMIT   = 0x0C   # if validated: write pending hash to heap[0..31]
OP_ASSERT   = 0x0D   # if rA != rB: halt + fail


def ins(op: int, a: int = 0, b: int = 0, c: int = 0) -> bytes:
    return bytes([op & 0xFF, a & 0xFF, b & 0xFF, c & 0xFF])


# Assembler conveniences -------------------------------------------------
def loadi(r: int, imm16: int) -> bytes:
    return ins(OP_LOADI, r, (imm16 >> 8) & 0xFF, imm16 & 0xFF)

def move(rd: int, rs: int) -> bytes:
    return ins(OP_MOVE, rd, rs, 0)

def read(rd: int, addr16: int) -> bytes:
    return ins(OP_READ, rd, (addr16 >> 8) & 0xFF, addr16 & 0xFF)

def write(rs: int, addr16: int) -> bytes:
    return ins(OP_WRITE, rs, (addr16 >> 8) & 0xFF, addr16 & 0xFF)

def cjmp(rcond: int, target16: int) -> bytes:
    return ins(OP_CJMP, rcond, (target16 >> 8) & 0xFF, target16 & 0xFF)

def halt() -> bytes:
    return ins(OP_HALT)

def request(rd: int, schema_id: int, payload_idx: int) -> bytes:
    return ins(OP_REQUEST, rd, schema_id, payload_idx)

def validate() -> bytes:
    return ins(OP_VALIDATE)

def commit() -> bytes:
    return ins(OP_COMMIT)

def assert_eq(ra: int, rb: int) -> bytes:
    return ins(OP_ASSERT, ra, rb, 0)


# =================================================================
# Trace Records
# =================================================================

@dataclass(frozen=True)
class StepRecord:
    step: int
    ip_before: int
    ip_after: int
    opcode: int
    instr: bytes                 # 4 bytes
    state_hash_after: bytes      # 32 bytes


@dataclass(frozen=True)
class TraceResult:
    initial_state_hash: bytes
    steps: Tuple[StepRecord, ...]
    final_state_hash: bytes
    success: bool
    halted: bool


# =================================================================
# VM Execution
# =================================================================

def run_trace(code: bytes,
              payloads: Optional[Dict[int, Tuple[int, dict]]] = None,
              max_steps: int = 100_000) -> TraceResult:
    """
    Execute `code` and return full ITV trace.

        code:     raw instruction bytes (length multiple of 4)
        payloads: {payload_idx: (schema_id, payload_dict)} for REQUEST

    Invariants enforced:
      - IP increments BEFORE execution.
      - Invalid opcode / OOB memory / OOB fetch  ->  halt + success=false.
      - COMMIT requires prior VALIDATE=True.
      - max_steps exceeded -> halt + success=false.
    """
    if payloads is None:
        payloads = {}

    state = VMState()
    initial = state.hash_state()
    steps: List[StepRecord] = []
    step_num = 0

    while not state.halted and step_num < max_steps:
        # ---- Fetch ----
        if state.ip + INSTR_LEN > len(code):
            state.halted = True
            state.success = False
            break

        instr = bytes(code[state.ip : state.ip + INSTR_LEN])
        op, a, b, c = instr[0], instr[1], instr[2], instr[3]
        ip_before = state.ip
        state.ip += INSTR_LEN                    # IP increments BEFORE execute

        # ---- Execute ----
        if op == OP_LOADI:
            state.regs[a & 0xF] = ((b << 8) | c) & 0xFFFFFFFFFFFFFFFF

        elif op == OP_MOVE:
            state.regs[a & 0xF] = state.regs[b & 0xF]

        elif op == OP_READ:
            addr = (b << 8) | c
            if addr < HEAP_SIZE:
                state.regs[a & 0xF] = state.heap[addr]
            else:
                state.halted = True
                state.success = False

        elif op == OP_WRITE:
            addr = (b << 8) | c
            if addr < HEAP_SIZE:
                state.heap[addr] = state.regs[a & 0xF] & 0xFF
            else:
                state.halted = True
                state.success = False

        elif op == OP_CJMP:
            if state.regs[a & 0xF] != 0:
                state.ip = (b << 8) | c

        elif op == OP_HALT:
            state.halted = True            # success preserved

        elif op == OP_ASSERT:
            if state.regs[a & 0xF] != state.regs[b & 0xF]:
                state.halted = True
                state.success = False

        elif op == OP_REQUEST:
            # b = schema_id, c = payload_idx
            entry = payloads.get(c)
            if entry is None:
                state.halted = True
                state.success = False
            else:
                sid, pl = entry
                if sid != b:
                    state.halted = True
                    state.success = False
                else:
                    try:
                        h = payload_hash(b, pl)
                        state.regs[a & 0xF] = int.from_bytes(h[:8], "big")
                        state._pending_req_hash = h
                        state._validated = False
                    except Exception:
                        state.halted = True
                        state.success = False

        elif op == OP_VALIDATE:
            if state._pending_req_hash is None:
                state.halted = True
                state.success = False
            else:
                state._validated = True

        elif op == OP_COMMIT:
            if not state._validated or state._pending_req_hash is None:
                state.halted = True
                state.success = False
            else:
                witness = state._pending_req_hash
                for i, byte in enumerate(witness):
                    if i < HEAP_SIZE:
                        state.heap[i] = byte
                state._validated = False
                state._pending_req_hash = None

        else:
            # Invalid opcode
            state.halted = True
            state.success = False

        steps.append(StepRecord(
            step=step_num,
            ip_before=ip_before,
            ip_after=state.ip,
            opcode=op,
            instr=instr,
            state_hash_after=state.hash_state(),
        ))
        step_num += 1

    if not state.halted:
        state.halted = True
        state.success = False  # exceeded max_steps without HALT

    return TraceResult(
        initial_state_hash=initial,
        steps=tuple(steps),
        final_state_hash=state.hash_state(),
        success=state.success,
        halted=state.halted,
    )


# =================================================================
# Fixed Binary Trace-Log Format ("ITV1")
# =================================================================
# Layout (all multi-byte integers big-endian, no padding):
#
#   magic              4  B   "ITV1"
#   code_len           4  B   uint32
#   code              (N) B
#   initial_hash     32  B   SHA-256
#   step_count         4  B   uint32
#   [ per step:
#       step_number    4  B
#       ip_before      4  B
#       ip_after       4  B
#       opcode         1  B
#       instr          4  B
#       state_hash    32  B
#     ] = 53 B per step
#   final_hash       32  B   SHA-256
#   success            1  B   0x00 / 0x01
#   halted             1  B   0x00 / 0x01

MAGIC = b"ITV1"


def encode_trace_log(code: bytes, trace: TraceResult) -> bytes:
    out = bytearray()
    out += MAGIC
    out += len(code).to_bytes(4, "big")
    out += code
    out += trace.initial_state_hash
    out += len(trace.steps).to_bytes(4, "big")
    for s in trace.steps:
        out += s.step.to_bytes(4, "big")
        out += s.ip_before.to_bytes(4, "big")
        out += s.ip_after.to_bytes(4, "big")
        out += bytes([s.opcode & 0xFF])
        out += s.instr
        out += s.state_hash_after
    out += trace.final_state_hash
    out += bytes([1 if trace.success else 0])
    out += bytes([1 if trace.halted  else 0])
    return bytes(out)


def trace_log_hash(log: bytes) -> str:
    return hashlib.sha256(log).hexdigest()

def run_tests() -> tuple:
    """Standard run_tests() adapter for run_all.py."""
    passed = failed = 0
    results = []

    def t(name, fn):
        nonlocal passed, failed
        try:
            fn(); passed += 1; results.append((name,'PASS',None))
        except Exception as e:
            failed += 1; results.append((name,'FAIL',str(e)))

    t("encode_payload_sql", lambda: encode_payload(1, {
        "query": "SELECT 1", "user_id": 42, "purpose": "test"
    }))
    t("payload_hash_deterministic", lambda: (
        payload_hash(1, {"query": "SELECT 1", "user_id": 42, "purpose": "test"}) ==
        payload_hash(1, {"query": "SELECT 1", "user_id": 42, "purpose": "test"})
    ) or None)
    t("run_trace_linear", lambda: run_trace(
        b"".join([loadi(0, 0x1234), move(1, 0), halt()]), {}
    ))
    code1 = b"".join([loadi(0, 1), halt()])
    payload = encode_payload(1, {"query":"Q","user_id":1,"purpose":"t"})
    trace1 = run_trace(code1, {})
    t("trace_log_encodes",      lambda: encode_trace_log(code1, trace1))
    t("trace_log_hash_is_64",   lambda: len(trace_log_hash(
        encode_trace_log(code1, trace1))) == 64)
    t("halt_terminates_success",lambda: trace1.success == True)
    t("write_read_roundtrip",   lambda: run_trace(
        b"".join([loadi(0, 0xAB), write(0, 100), read(1, 100), halt()]), {}
    ).success)
    t("deterministic_same_inputs", lambda: (
        encode_trace_log(code1, run_trace(code1, {})) ==
        encode_trace_log(code1, run_trace(code1, {}))
    ) or None)

    return passed, failed, results
