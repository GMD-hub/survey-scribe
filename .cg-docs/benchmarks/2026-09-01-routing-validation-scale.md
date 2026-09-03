# Routing Validation Scale Evidence

## Result

- Status: passed
- Logical nodes: 1,000
- Accepted edges: 3,000
- Validation runs in measured interval: 2
- Measured two-run duration: 0.774177 seconds
- Peak traced Python allocation: 5,018,595 bytes (4.79 MiB)
- Pytest case duration: 0.933 seconds
- Timing threshold: none

Both validation runs returned identical empty diagnostic and loop tuples. The
test completed without recursion failure and uses no graph dependency.

## Hardware

- Host: generic Windows CI VM
- Platform: `Windows-10-10.0.20348-SP0`
- System: VMware Virtual Platform, AMD64
- CPU: Intel Xeon Platinum 8462Y+, 16 logical processors exposed to the VM
- Physical memory exposed to the VM: 128 GiB
- Python: CPython 3.11.15

## Method

`tests/unit/test_routing_validation.py` generates a deterministic acyclic graph
in memory. It first adds the 999-edge forward chain, then adds increasing forward
offsets until the graph has exactly 3,000 unique edges. Graph construction is
outside the measured interval.

The test starts `tracemalloc`, starts `time.perf_counter`, calls
`validate_routing_graph` twice, records elapsed time, reads the `tracemalloc`
peak, and then stops tracing. Pytest records the hardware, graph size, duration,
and peak allocation as JUnit properties. Duration and peak memory are evidence,
not pass/fail thresholds; correctness, determinism, graph size, and successful
iterative completion are the assertions.

Command:

```text
uv run pytest tests/unit/test_routing_validation.py::test_scale_1000_nodes_3000_edges_is_iterative_deterministic_and_measured -q -o junit_family=legacy --junitxml="<external-temp>/routing-scale.xml"
```

Command result: `1 passed in 1.13s`.
