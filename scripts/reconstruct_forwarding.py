#!/usr/bin/python3

"""
Reconstruct per-flow forwarding graphs from network summary(s)
"""

from argparse import ArgumentParser
import nopticon
import os
import pygraphviz

"""
Make per-flow graphs from a network summary
"""
def make_graphs(settings, link_summary, timestamp='end'):
    for flow in link_summary.get_flows():
        make_graph(settings, flow, link_summary.get_links(flow), timestamp)

"""
Make flow-specific graph
"""
def make_graph(settings, flow, links, timestamp):
    # Create graph
    graph = pygraphviz.AGraph(strict=False, directed=True)
    for source, targets in links.items():
        for target in targets:
            graph.add_edge(source, target)

    # Determine graph path
    graph_dir = os.path.join(settings.graphs_path, str(flow).replace('/','_'))
    os.makedirs(graph_dir, exist_ok=True)
    graph_path = os.path.join(graph_dir, '%s.png' % (timestamp))

    # Render graph
    graph.layout()
    graph.draw(graph_path, prog='dot')

def main():
    # Parse arguments
    arg_parser = ArgumentParser(description='Reconstruct per-flow forwarding graphs from network summary(s)')
    arg_parser.add_argument('-s', '--summary', dest='summary_path', 
            action='store', required=True, help='Path to summary JSON file')
    arg_parser.add_argument('-g', '--graphs', dest='graphs_path', 
            action='store', required=True, help='Path to store graphs')
    settings = arg_parser.parse_args()

    # Iterate over all summaries
    with open(settings.summary_path, 'r') as sf:
        for i, summary_json in enumerate(sf):
            link_summary = nopticon.LinkSummary(summary_json)
            make_graphs(settings, link_summary, '%010d' % (i))

if __name__ == '__main__':
    main()
