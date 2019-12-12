#!/usr/bin/python3

"""
Check whether all intents appear in a network summary
"""

from argparse import ArgumentParser
import ipaddress
import json
import math
import nopticon

def get_edge_rank(summary, flow, edge):
    rank = summary.get_edge_rank(flow, edge)
    if (rank is None):
        return (-1, -1, -1, [])
    edges = summary.get_edges(flow)
    ranks = sorted(set([summary.get_edge_rank(flow, edge) for edge in edges.keys()]),
            reverse=True)
    flow_rank = ranks.index(rank) + 1
    flow_percentile = flow_rank/len(ranks) * 100
    history = summary.get_edge_history(flow, edge)
    return (rank, flow_rank, flow_percentile, history)


def check_reachability(policy, summary):
    return get_edge_rank(summary, policy._flow, policy.edge())

def main():
    # Parse arguments
    arg_parser = ArgumentParser(description='Check whether intents appear in a network summary')
    arg_parser.add_argument('-s','--summary', dest='summary_path',
            action='store', required=True, help='Path to summary JSON file')
    arg_parser.add_argument('-p','--policies', dest='policies_path',
            action='store', help='Path to policies JSON file')
    arg_parser.add_argument('-e','--extras', dest='extras', action='store_true',
            help='Output edges that do not correspond to any policies')
    arg_parser.add_argument('-c', '--coerce', dest='coerce',
            action='store_true',
            help='Coerce path-preference policies to reachability policies')
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

    # Load policies
    if (settings.policies_path is not None):
        with open(settings.policies_path, 'r') as pf:
            policies_json = pf.read()
        policies = nopticon.parse_policies(policies_json)
    else:
        policies = []

    # Coerce path preference policies to reachability policy
    if (settings.coerce):
        for idx, policy in enumerate(policies):
            if policy.isType(nopticon.PolicyType.PATH_PREFERENCE):
                policies[idx] = policy.toReachabilityPolicy()

    # Check policies
    for policy in policies:
        if policy.isType(nopticon.PolicyType.REACHABILITY):
            reach_result = check_reachability(policy, summary)
            if (reach_result[0] >= settings.threshold):
                satisfied = 'satisfied'
                num_satisfied += 1
            else:
                satisfied = 'unsatisfied'
            print('Policy %s %f %d %f %s %s' % (policy, reach_result[0],
                reach_result[1], reach_result[2], satisfied, reach_result[3]))
    # Indicate how many policies were found
    print('%d out of %d policies were found.' % (num_satisfied, len(policies)))

    # Check for extra edges
    if (settings.extras):
        # Get all edges in policies
        policy_edges = {}
        for policy in policies:
            if policy.isType(nopticon.PolicyType.REACHABILITY):
                if policy._flow not in policy_edges:
                    policy_edges[policy._flow] = []
                policy_edges[policy._flow].append(policy.edge())

        # Identify extra edges
        print("Extras:")
        for flow in summary.get_flows():
            first_edge_for_flow = True
            for edge in summary.get_edges(flow):
                if flow not in policy_edges or edge not in policy_edges[flow]:
                    rank_result = get_edge_rank(summary, flow, edge)
                    if (rank_result[0] >= settings.threshold):
                        if (first_edge_for_flow):
                            print(flow)
                            first_edge_for_flow = False
                        edge_str = '%s -> %s' % (edge)
                        print('\t%s (%.3f %4d %3.3f)' % (edge_str.ljust(50),
                            rank_result[0], rank_result[1], rank_result[2]))

if __name__ == '__main__':
    main()
