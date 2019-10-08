#! /usr/bin/python3


"""
  
  Compute Node Equivalence Classes for Reachability summaries

"""

import nopticon
from argparse import ArgumentParser

def height(succ, node, memo, gas = 200):
    if gas == 0:
        return 0
    if node not in memo:
        if node in succ:
            memo[node] = 1 + max([height(succ, s, memo, gas-1) for s in succ[node]])
        else:
            memo[node] = 0
    return memo[node]

def loop_free(succ):
    searched = set()
    for n in succ.keys():
        if n in searched:
            continue
        else:
            searched.add(n)

        seen = set()
        worklist = [n]
        while len(worklist) > 0:
            v = worklist[0]
            if v in seen:
                return False
            else:
                seen.add(v)
                
            if v in searched:
                continue
            else:
                searched.add(v)

            for s in succ[v]:
                worklist.append(s)
        
    return True            
    
def compute_flow_NECs(edges):
    adj = { source: set([ target for src, target in edges
                          if src == source])
            for source,_ in edges }
    op_adj = { target : set([source for source, tgt in edges
                             if tgt == target])
               for _, target in edges }

    # Compute the join of the two key sets
    nodes = set(adj.keys()).union(set(op_adj.keys()))
    memo = {}
    op_memo = {}
    return { n: (height(adj, n, memo), height(op_adj, n, op_memo)) for n in nodes }
    
    

def compute_general_NECs(threshold, reach):
    all_fNECs = {}
    for f in reach.get_flows():
        necs = compute_flow_NECs([edge for edge in reach.get_edges(f).keys()
                                  if threshold is None or reach.get_edge_rank(f,edge) >= threshold])
        # print(f,necs)
        # print()
        for n, eqc in necs.items():
            if n in all_fNECs:
                all_fNECs[n].append((f,eqc))
            else:
                all_fNECs[n] = [(f,eqc)]

    for n in all_fNECs.keys():
        all_fNECs[n] = sorted([eqc for _,eqc in all_fNECs[n]])

    gNECs = set()
    for n in all_fNECs.keys():
        for cls in gNECs:
            if n in cls: #if we've already placed n in an equivalence class
                continue
        cls = (n,)
        for m in all_fNECs.keys():
            if n != m:
                if all_fNECs[n] == all_fNECs[m]:
                    cls += (m,)
        gNECs.add(tuple(sorted(cls)))
        
    return gNECs
            
    


def main():
    parser = ArgumentParser(description = "Compute Node Equivalence Classes for a given Reachability Summary and rDNS")
    parser.add_argument("-t", "--threshold", default=None, type=int, required=False,
                        help="The minimum rank to consider out of 100, e.g. A value of 75 corresponds to a rank of 0.75 ")
    parser.add_argument("-s", "--sigfigs", default=2, type=int, required=False,
                        help="The number of sig figs for the rank values")
    parser.add_argument("summary", help="The filepath to the reachability summary in JSON form")
    settings = parser.parse_args()

    rs = None
        
    with open(settings.summary) as reach_fp:
        rs = nopticon.ReachSummary(reach_fp.read(), settings.sigfigs)

    if settings.threshold is None:
        gNEC_outputs = []
        data = [] #list of pairs of thresholds and gNEC indexes from gNEC_outputs
        for threshold in range(0,101):
            gNECstr = str(sorted(compute_general_NECs(float(float(threshold))/100.0, rs), keys= lambda x: x[0]))
            if gNECstr in gNEC_outputs:
                gNEC_idx = len(gNEC_outputs)
                gNEC_outputs.append(gNECstr)
            else:
                gNEC_idx = gNEC_outputs.idx(gNECstr)

            data.append((threshold, gNEC_idx))

        lastthresh = None
        goat_NEC = None
        goat_ival = None
        goat_dur = None
        curr_NEC = None
        curr_ival = None
        for t, nec in data:
            if curr_NEC is None or curr_ival is None:
                curr_NEC = nec
                curr_ival = [(t,None)]
                lastthresh = t
            elif curr_NEC == nec:
                lastthresh = t
            else: # examining a new equivalence class!
                # close out the old one
                
                curr_ival[-1] = (curr_ival[-1][0], lastthresh)
                curr_dur = max([ end - start for start, end in curr_ival ])
                                
                if goat_NEC is None or goatThresh is None or goat_dur is None or\
                   curr_dur > goat_dur:
                    goat_NEC = curr_NEC
                    goat_ival = curr_ival
                    goat_dur = curr_dur
                #else:
                    #noop

                # create a new equivalence class!
                curr_NEC = nec
                curr_ival = [(t,None)]
                lastthresh = t

        print(gNEC_outputs[goat_NEC])
        print(goat_ival)
        
    else:
        if settings.threshold > 100 or settings.threshold < 0:
            print("Threshold must be between 0 and 100")
            return 1
            
        gNECs = compute_general_NECs(float(float(settings.threshold)/100.0), rs)

        # print each equivalence class
        for eqC in sorted(gNECs, key = lambda x: x[0]): 
            print(*eqC)
        
if __name__ == "__main__":
    main()
