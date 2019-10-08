#! /usr/bin/python

"""
This script is the central end-to-end experiment driver that evaluates nopticon's performance for SIGCOMM
"""

from kmodes.kprototypes import KPrototypes
from sklearn.cluster import DBSCAN, KMeans, AgglomerativeClustering

from argparse import ArgumentParser
import nopticon
import implied_properties
import equivalence as eq
import numpy as np
import matplotlib.pyplot as plt
import time

import matplotlib.pyplot as plt
plt.rcParams.update({'font.size': 12})
plt.rcParams.update({'figure.autolayout': True})

def cluster(summ, agg_classes = None):
    """
    Clusters summary info using DBSCAN if agg_classes is provided it uses K-Prototypes
    """
    all_prop = None
    prop = {}
    ranks = []
    for flow, edge in summ.get_flowedges():
        rank = round(summ.get_edge_rank(flow, edge), 2)
        if rank < 0.5:
            continue
        # else:
            # print(flow, edge, rank)

        policy = nopticon.ReachabilityPolicy({'flow' : flow,
                                              'source' : edge[0],
                                              'target' : edge[1]})
        prop[policy] = len(ranks)
        if agg_classes is not None:
            ranks.append([rank, agg_classes[edge[0]], agg_classes[edge[1]]])
        else:
            ranks.append([rank])

    if agg_classes is not None:
        kproto = KPrototypes(n_clusters=3, init='Huang')
        clust = kproto.fit_predict(np.matrix(ranks).A, categorical=[1,2])
    else:
        agg = KMeans(n_clusters=2, n_jobs=2) # linkage="complete")
        clust = agg.fit(ranks).labels_

    assert len(clust) == len(ranks)
    means = {}
    high = None
    for k in set(clust):
        kranks = [ranks[idx][0] for idx in prop.values() if clust[idx] == k]
        means[k] = sum(kranks)/len(kranks)
        if high is None or means[k] > means[high]:
            high = k

    for p,idx in prop.items():
        if clust[idx] == high:
            # print("\tHIGH:", ranks[idx], p)
            summ.mark_cluster_accepted(p.flow(), p.edge())
        # else:
            # print("\tlow:", ranks[idx], p)
    return


def equivalence(summ,threshold):
    gNECs = eq.compute_general_NECs(0.5, summ)
    get_node_eqc_id = {}
    for idx,cls in enumerate(sorted(gNECs, key=lambda x: x[0])):
        for node in cls:
            get_node_eqc_id[node] = idx

    return get_node_eqc_id        

    
def threshold(summ, t):
    """
    Thresholds summ >= t
    """
    for f,e in summ.get_flowedges():
        if summ.get_edge_rank(f,e) > t:
            summ.mark_above_threshold(t,f,e)
    
def evaluate(summ, pref_summ, policies, artefacts, pref_policies, cluster, implied, threshold, baseline = False):
    """
    Checks agreement between summ and policies, according to which experiments were run
    returns a tuple of Precision, Recall, Accuracy
    """
    
    true_positive_count = 0
    allowed_error_count = 0
    true_negative_count = 0
    false_positive_count = 0
    false_negative_count = 0
    falses = set([])
    for flow, edge in summ.get_flowedges():
        pol = nopticon.ReachabilityPolicy({'flow' : flow,
                                          'source' : edge[0],
                                          'target': edge[1]})
        if baseline or summ.is_insight(flow = flow,
                                       edge = edge,
                                       cluster = cluster,
                                       threshold = threshold,
                                       implied = implied):
            if pol in policies:
                true_positive_count += 1
                # print("TP:", pol, summ.get_edge_rank(flow,edge))
            else:
                if pol in artefacts:
                    allowed_error_count += 1
                # print("FP", pol, summ.get_edge_rank(flow,edge))
                false_positive_count += 1
            
        else:

            if pol in policies:
                # print("FALSE--", pol, summ.get_edge_rank(flow, edge))                
                false_negative_count += 1
            else:
                # print("TRUE--", pol, summ.get_edge_rank(flow, edeg))
                true_negative_count += 1


    if true_positive_count + false_positive_count == 0:
        prec = 0
        allowed_error = 0
        rec = 0
    else:
        prec = true_positive_count/(true_positive_count + false_positive_count)
        allowed_error =  allowed_error_count/(true_positive_count + false_positive_count)
        rec  = true_positive_count/len(policies)
        
    acc  = (true_positive_count + allowed_error_count + true_negative_count) / (true_positive_count + true_negative_count + false_negative_count + false_positive_count)
    if prec + rec > 0:
        # f1score = 2.0*((prec + allowed_error)*rec)/(prec + allowed_error + rec)
        f1score = 2.0*((prec)*rec)/(prec  + rec)
    else:
        f1score = 0.0

    pref_TP_count = 0
    for pref in pref_summ.preferences():
        if pref in pref_policies:
            pref_TP_count += 1

    # for p in pref_policies:
    #     if p not in pref_summ.preferences():
    #         print("False NEG:", p)

    # print("")
    # print("")

    if len(pref_summ.preferences()) == 0 or len(pref_policies) == 0:
        pref_prec = None
        pref_rec = None
        pref_f1score = None
    else:
        pref_prec = pref_TP_count / len(pref_summ.preferences())
        pref_rec = pref_TP_count / len(pref_policies)
        pref_f1score = 2 * (pref_prec*pref_rec) / (pref_prec + pref_rec)
    
    return (prec, allowed_error, rec, acc, f1score, pref_prec, pref_rec, pref_f1score) 

def exp_quality_str(summ, pref_summ, policies, artefacts, pref_policies, datafile, naive_cluster, agg_cluster, implied, threshold, time, baseline = False):
    precision,allowed_error,recall,accuracy,f1score,pref_prec,pref_rec,pref_f1score =  evaluate(summ, pref_summ,
                                                                                                policies, artefacts,
                                                                                                pref_policies,
                                                                                                implied = implied,
                                                                                                threshold = threshold,
                                                                                                cluster = naive_cluster or \
                                                                                                agg_cluster, baseline = baseline)
    return (datafile, agg_cluster, naive_cluster, implied,
            threshold, baseline, precision, allowed_error, recall, accuracy, f1score, time, pref_prec, pref_rec, pref_f1score)


def all_pairs(settings):
    if settings.completionist:
        return [(n, a, i, t)
                for n in set([settings.do_naive_clustering, False])
                for a in set([settings.do_agg_clustering, False])
                for i in set([settings.remove_implied_properties, False])
                for t in set([settings.threshold])
                if n != a or (not n and not a)]
    else:
        return [(settings.do_naive_clustering,
                settings.do_agg_clustering,
                settings.remove_implied_properties,
                settings.threshold)]

def write_experiments(to_directory, from_data):
    baseline = sorted([(prettify_name(df), prec, err, rec, acc, f1, tm, pfp, pfr, pff)
                            for df, ag, na, imp, thrsh, bl, prec, err, rec, acc, f1,tm, pfp, pfr, pff in from_data
                            if bl and not na and not ag and not imp], key = lambda x: x[0])
    naive_cluster = sorted([(prettify_name(df), prec, err, rec, acc, f1, tm, pfp, pfr, pff)
                            for df, ag, na, imp, thrsh, bl, prec, err, rec, acc, f1,tm, pfp, pfr, pff in from_data
                            if na and not ag and not imp and not bl], key = lambda x: x[0])
    agg_cluster = sorted([(prettify_name(df), prec, err, rec, acc, f1, tm, pfp, pfr, pf)
                          for df, ag, na, imp, thrsh,bl, prec, err, rec, acc, f1, tm, pfp, pfr, pf in from_data
                          if ag and not imp and not bl], key=lambda x: x[0])
    remove_consequences = sorted([(prettify_name(df), prec, err, rec, acc, f1, tm, pfp, pfr, pf)
                                  for df, ag, na, imp, thrsh, bl,prec, err, rec, acc, f1, tm, pfp, pfr, pf in from_data
                                  if imp and not ag and not na and not bl], key=lambda x: x[0])
    naive_remove = sorted([(prettify_name(df), prec, err, rec, acc, f1, tm, pfp, pfr, pf)
                           for df, ag, na, imp, thrsh, bl,prec, err, rec, acc, f1, tm, pfp, pfr, pf in from_data
                           if na and imp and not ag and not bl], key=lambda x: x[0])
    agg_remove = sorted([(prettify_name(df), prec, err, rec, acc, f1, tm, pfp, pfr, pf)
                         for df, ag, na, imp, thrsh, bl, prec, err, rec, acc, f1, tm, pfp, pfr, pf in from_data
                         if ag and imp and not bl], key = lambda x: x[0])

    

    # if "F" in naive_cluster[0][0] or "F" in agg_cluster[0][0]:
    lines = [  baseline, naive_cluster, remove_consequences, agg_cluster, naive_remove,   agg_remove]
    names = ["BASE",      "KMeans", "Topo",   "KProto", "KMeans&Topo", "KProto&Topo"]
    # else:
    #     lines = [naive_cluster, remove_consequences, naive_remove]
    #     names = [        "NAI",               "REM",    "NAI_REM"]

    
    bar( directory = to_directory,
         lines = lines,
         exp_names = names,
         stack_idxs = [(0,1), (0,2)],
         stack_names = ["precision", "artefact"])
    
    plot( directory = to_directory,
          lines = lines,
          names = names,
          views =   [      (0,1),      (0,2),    (0,3),      (0,4),      (0,5), (0,6),
                                (0,7),         (0,8),           (0,9)],
          y_axes =  ["precision", "artefact", "recall", "accuracy", "F1-score", "time",
                     "pref_precision", "pref_recall", "pref_F1-score"])

    

def bar(directory, lines, exp_names, stack_idxs, stack_names, x_axis = "simulation"):
    assert len(lines) == len(exp_names)
    assert len(stack_idxs) == len(stack_names)

    for idx, name in enumerate(exp_names):
        line = lines[idx]
        print(name)
        stacks = [([p[x] for p in line], [p[y] for p in line])
                  for (x,y) in stack_idxs]
        plt.figure(figsize=(8,4))
        for stack_i,(xs,ys) in enumerate(stacks):
            print(stack_names[stack_i])
            print(xs)
            print(ys)
            if stack_i > 0:
                bottom = [0 for y in ys]
                for idx in range(0,stack_i):
                    _,smaller_ys = stacks[idx]
                    bottom = [b + smaller_ys[i] for i,b in enumerate(bottom)]
                plt.bar(xs, ys, bottom=bottom, label=stack_names[stack_i])
            else:    
                plt.bar(xs, ys, label = stack_names[stack_i])
        plt.ylabel("")
        plt.xlabel("simulation")
        plt.xticks(rotation=90)
        plt.legend()
        plt.savefig("{}/{}-{}-bar.pdf".format(directory,name,'_'.join(stack_names)))
        plt.close("all")
    
def plot(directory, lines, names, views, y_axes, x_axis = "simulation"):
    assert len(views) == len(y_axes)
    assert len(lines) == len(names)
    linestyles = ['-','-.','--','-',':',':']
    
    for idx, (x_idx,y_idx) in enumerate(views):
        plt.figure(figsize=(4,4))
        y_axis_label = y_axes[idx]
        for l_idx, line in enumerate(lines):
            xs = [ p[x_idx] for p in line ]
            ys = [ (p[y_idx] if p[y_idx] is not None else 0) + .002*l_idx for p in line ]
            # print(names[l_idx], y_axis_label)
            # print(lines)
            # print(xs)
            # print(ys)
            plt.plot(tuple(xs), tuple(ys), label = names[l_idx], linestyle=linestyles[l_idx])
            
        plt.ylabel(y_axis_label)
        plt.xlabel(x_axis)
        plt.xticks(rotation=90)
        # if "pref" not in y_axis_label:
        #     plt.legend()
        plt.ylim(0,1.1)
        plt.savefig("{}/{}-{}.pdf".format(directory, x_axis, y_axis_label))
        plt.close('all')


def prettify_name(name):
    outputname = ""
    if "fattree-4" in name:
        outputname += "F4"
    elif "fattree-6" in name:
        outputname += "F6"
    elif "fattree-8" in name:
        outputname += "F8"
    
    elif "Arnes" in name:
        outputname += "A"
    elif "Sinet" in name:
        outputname += "S"
    elif "Bics" in name:
        outputname += "B"
    elif "Colt" in name:
        outputname += "C"
    elif "CrlNetworkServices" in name:
        outputname += "N"
    elif "Latnet" in name:
        outputname += "L"
    elif "TataNld" in name:
        outputname += "T"
    elif "GtsCe" in name:
        outputname += "G"
    else:
        outputname += "?"

    if "4" in name and "F4" not in outputname:
        outputname += "-04"
    elif "8" in name:
        outputname += "-08"
    elif "16" in name:
        outputname += "-16"
    elif "32" in name:
        outputname += "-32"
    elif "64" in name:
        outputname += "-64"
    
    return outputname
    
def main():
    parser = ArgumentParser(description="Run experiments on nopticon data for SIGCOMM")
    parser.add_argument("simulations",
                        help="A CSV file where the first column is a simulation dataset, the second column is the topology file for the simulation, and the third column is the policies file for the simulation")
    parser.add_argument("-c", "--do-naive-clustering", dest="do_naive_clustering", action="store_true",
                        default=False, help="setting this flag performs naive clustering")
    parser.add_argument("-C", "--do-agg-clustering", dest="do_agg_clustering", action="store_true",
                        default=False, help="setting this flag overrides the naive clustering flag and performes equivalence class based aggregation clustering")
    parser.add_argument("-I", "--remove-implied-properties", dest="remove_implied_properties", action="store_true",
                        default=False, help="Setting this flag executes naive clustering")
    parser.add_argument("-t", "--threshold", type=float, default=None, help="Providing this flag runs the experiments after discarding values below t")
    parser.add_argument("-p", "--completionist", action="store_true", default = False, help="setting this flag tests all combinations underneath the provided combination.")
    parser.add_argument("-V", "--visualize", default=None, help="A directory into which charts are output")
    parser.add_argument("-o", "--outfile", dest="outfile", default=None,
                        help="The output csv file")


    settings = parser.parse_args()
    
    simulations = []
    with open(settings.simulations, 'r') as sim_fp:
        simulations = sim_fp.readlines()


    output = []
    for sim in simulations:
        datafile, topofile, polfile = sim.split(',')
        fwd_summary, topo, policies = (None, None, None)
        with open(datafile.strip(), 'r') as data_fp:
            fwd_str = data_fp.read()
            if len(fwd_str) < 10:
                continue
            if settings.visualize is None:
                loc = ""
            else:
                loc = settings.visualize + prettify_name(datafile)
            fwd_summary = nopticon.ReachSummary(fwd_str, 9)#, loc = loc)
            pref_summary = nopticon.PrefSummary(fwd_str, 9)
        with open(topofile.strip(), 'r') as topo_fp:
            topo = implied_properties.Topo(topo_fp.read())
        with open(polfile.strip(), 'r') as pol_fp:
            simple_policies = nopticon.parse_policies(pol_fp.read())

        coerced_policies = []
        artefacts = []
        pref_policies = []
        for idx, policy in enumerate(simple_policies):
            if policy.isType(nopticon.PolicyType.PATH_PREFERENCE):
                coerced_policies = policy.toReachabilityPolicy() + coerced_policies
                artefacts = policy.toImpliedReachabilityPolicies() + artefacts
                pref_policies.append(policy)
            else:
                coerced_policies.append(policy)


        # evaluate every result for the collected data
        for naive, agg, imp, thresh in all_pairs(settings):
            start_time = time.time()

            if thresh is not None:
                # threshold
                threshold(fwd_summary, settings.threshold)

            if agg:
                # do aggregated clustering
                cluster(fwd_summary, equivalence(fwd_summary, settings.threshold))
            elif naive:
                # do naive clustering
                cluster(fwd_summary)

            if imp:
                # remove implied properties
                implied_properties.mark_implied_properties(fwd_summary, topo, settings.threshold)
                
            end_time = time.time()
            print("EXP")
            output.append(exp_quality_str(fwd_summary, pref_summary, coerced_policies, artefacts, pref_policies, datafile, naive, agg, imp, thresh, round(end_time - start_time, 3)))

            fwd_summary.clear()

        output.append(exp_quality_str(fwd_summary, pref_summary, coerced_policies, artefacts, pref_policies, datafile, False, False, False, None, 0, baseline = True))


    if settings.visualize is not None:
        write_experiments(to_directory=settings.visualize, from_data=output)

    output = [("simulation","agg_clustering","naive_clustering","reduction","threshold","precision","recall","accuracy","f1score")] + output

    outstr = '\n'.join([','.join([str(oel) for oel in o]) for o in output])
    if settings.outfile is None:
        print(outstr)
    else:
        with open(settings.outfile, 'w+') as out_fp:
            # print to outfile
            out_fp.write(outstr)
    return
        
if __name__ == "__main__":
    main()

