"""
V-Mut: mutation testing.

Two legs:
  * Python: mutate sentinel_hft.golden.risk_gate at runtime, assert the
    pytest suite catches each mutation. Runs everywhere Python runs.
  * RTL:    mutate rtl/*.sv on disk, rebuild Verilator + cocotb V-Parity,
    assert at least one decision diverges. Requires Verilator + cocotb.

The Python leg is the first-line check that the test corpus is "tight":
if I can flip a > to a < in the golden and the tests still pass, the
tests aren't really testing the gate. The RTL leg goes a step further and
verifies that the deployed bitstream's logic is equally well-tested.
"""
