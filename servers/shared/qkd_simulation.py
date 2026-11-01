"""Deterministic BB84 simulation for prototyping only; this is not physical QKD."""
from __future__ import annotations

import hashlib
import hmac
import random


def bb84_simulated_key(master_seed: bytes, session_challenge: bytes, *, qubits: int = 512) -> bytes:
    """Return the same simulated BB84 key on both configured nodes.

    Both services must be provisioned with the same private master seed. Qiskit's
    ideal Statevector simulator samples the quantum measurement outcomes; the
    shared seed makes the two local simulations reproducible. No quantum channel,
    hardware, or real-world eavesdropping security is modeled by this function.
    """
    if len(master_seed) < 32:
        raise ValueError("QKD_SIMULATION_SEED_B64 must decode to at least 32 bytes")
    if qubits < 128:
        raise ValueError("BB84 simulation needs at least 128 qubits")

    # Imports are delayed so services can run without Qiskit when the QKD
    # prototype is disabled.
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector

    sequence_seed = hmac.new(master_seed, b"pricewatchin-bb84-sequence\0" + session_challenge, hashlib.sha256).digest()
    sequence = random.Random(int.from_bytes(sequence_seed, "big"))
    alice_bits = [sequence.getrandbits(1) for _ in range(qubits)]
    alice_bases = [sequence.getrandbits(1) for _ in range(qubits)]
    bob_bases = [sequence.getrandbits(1) for _ in range(qubits)]

    bob_bits: list[int] = []
    for index, (bit, alice_basis, bob_basis) in enumerate(zip(alice_bits, alice_bases, bob_bases)):
        circuit = QuantumCircuit(1)
        if bit:
            circuit.x(0)
        if alice_basis:
            circuit.h(0)
        if bob_basis:
            circuit.h(0)
        measurement_seed = hmac.new(
            master_seed,
            b"pricewatchin-bb84-measure\0" + session_challenge + index.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        state = Statevector.from_instruction(circuit)
        state.seed(int.from_bytes(measurement_seed[:8], "big"))
        sampled = state.sample_memory(shots=1)[0]
        bob_bits.append(int(sampled))

    sifted = [index for index in range(qubits) if alice_bases[index] == bob_bases[index]]
    sequence.shuffle(sifted)
    check_count = max(16, len(sifted) // 4)
    check_indices = set(sifted[:check_count])
    mismatches = sum(alice_bits[index] != bob_bits[index] for index in check_indices)
    if mismatches / check_count > 0.11:
        raise ValueError("simulated BB84 detected an excessive error rate")

    shared_bits = [alice_bits[index] for index in sifted[check_count:]]
    if len(shared_bits) < 128:
        raise ValueError("not enough sifted BB84 bits for the prototype key")
    packed = bytes(
        sum(bit << (7 - (offset % 8)) for offset, bit in enumerate(shared_bits[start : start + 8]))
        for start in range(0, len(shared_bits), 8)
    )
    return hashlib.sha256(b"pricewatchin-bb84-simulated-key-v1\0" + session_challenge + packed).digest()
