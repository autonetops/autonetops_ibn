"""Protocol primitives shared by drivers (ADR-0008/0012).

Transports own HOW bytes reach a device (SSH CLI, gNMI, eAPI...); drivers own
the verb semantics on top (candidate vs merge, checkpoints, evidence).
"""
