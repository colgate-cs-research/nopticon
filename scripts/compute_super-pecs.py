#!/usr/bin/python3

"""
Aggregate flows from a Nopticon summary into sets of flows (super PECs) that
always exhibit equivalent forwarding behavior.  
"""

from argparse import ArgumentParser
import json
import nopticon

def assign_to_spec(flow, specs, summary):
    flow_edges = summary.get_edges(flow)
    for spec in specs:
        spec_edges = summary.get_edges(spec[0])
        if (flow_edges == spec_edges):
            spec.append(flow)
            return
    specs.append([flow])

def main():
    # Parse arguments
    arg_parser = ArgumentParser(description='Compute super PECs')
    arg_parser.add_argument('-s','--summary', dest='summary_path',
            action='store', required=True, help='Path to summary JSON file')
    arg_parser.add_argument('-t', '--threshold', default=0.5, type=float,
            required=False, help='The minimum rank to consider between 0 and 1')
    settings = arg_parser.parse_args()
    num_satisfied = 0

    if settings.threshold < 0 or settings.threshold > 1:
        print("Threshold must be between 0 and 1")
        return 1

    # Load summary
    with open(settings.summary_path, 'r') as sf:
        summary_json = sf.read()
    summary = nopticon.ReachSummary(summary_json)

    # Compute super PECs
    specs = []
    for flow in sorted(summary.get_flows()):
        assign_to_spec(flow, specs, summary)

    for spec in specs:
        print(','.join([str(flow) for flow in spec]))

if __name__ == '__main__':
    main()
