#!/usr/bin/python3

from argparse import ArgumentParser
import matplotlib.pyplot as plt
import nopticon

def main():
    # Parse arguments
    arg_parser = ArgumentParser(description='Construct a histogram of edge ranks in a reach summary')
    arg_parser.add_argument('-s','--summary', dest='summary_path',
            action='store', required=True, help='Path to summary JSON file')
    arg_parser.add_argument('-o','--output', dest='output_path',
            action='store', required=True, help='Path to histogram file')
    settings = arg_parser.parse_args()

    # Load summary
    with open(settings.summary_path, 'r') as sf:
        summary_json = sf.read()
    summary = nopticon.ReachSummary(summary_json)

    rank_distrib = [self.get_edge_rank(f,e) for (f,e) in self.get_flowedges()
            if self.get_edge_rank(f,e) > 0.9]
    plt.figure(figsize=(8,3))
    plt.hist(rank_distrib)
    plt.xlim(0.9,1.0)
    plt.savefig(settings.output_path)
    plt.close('all')

if __name__ == '__main__':
    main()
