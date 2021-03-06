#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""

This script analyses several more specifics features from captured data of any collector. It is the following step to the preprocessing.

"""

import experiment_manifest as exp
import file_manager as f
import pandas as pd
import radix


# FUNCTIONS
def get_change_index_per_column(column, from_index, to_index):
    aux_element = column[from_index]
    indexes = [from_index]

    for i in range(from_index, to_index):
        element = column[i]
        if element != aux_element:
            indexes.append(i)
            aux_element = element

    return indexes


def get_visibility_time_per_prefix(prefix_times, prefix_pref_types, experiment_from_time, experiment_to_time, window):
    experiment_time = experiment_to_time - experiment_from_time
    accum_time = 0

    print prefix_times
    print prefix_pref_types
    updates_per_prefix = len(prefix_times)
    first_window_i = window[0]
    last_window_i = window[-1]

    for i in window:

        current_pref_type = prefix_pref_types[i]
        current_time = prefix_times[i]

        if updates_per_prefix == 1 and (current_pref_type == 'B' or current_pref_type == 'A'):
            accum_time = experiment_to_time - current_time
        elif current_pref_type == 'A' and i != first_window_i and prefix_pref_types[i - 1] != 'W':
            previous_time = prefix_times[i - 1]
            # sometimes there are advises out of experiment window time
            # don't care about this because load_raw_data code discard these entries
            if i == last_window_i:
                accum_time += (experiment_to_time - previous_time)
            elif first_window_i < i < last_window_i:
                accum_time += current_time - previous_time
        elif current_pref_type == 'W' and i != first_window_i and prefix_pref_types[i - 1] != 'W':
            previous_time = prefix_times[i - 1]
            accum_time += current_time - previous_time

    return accum_time / experiment_time


def split_data_per_monitor(df):
    updates_per_monitor = {}

    # Get uniques monitor values
    monitors = df['MONITOR'].unique().tolist()

    for monitor in monitors:
        monitor_rows = df['MONITOR'] == monitor
        update_prefixes = df[monitor_rows]['PREFIX'].tolist()
        update_pref_types = df[monitor_rows]['pref_type'].tolist()
        update_times = df[monitor_rows]['TIME'].tolist()
        updates_per_monitor[monitor] = pd.DataFrame(
            {'PREFIX': update_prefixes, 'pref_type': update_pref_types, 'TIME': update_times})

    return updates_per_monitor


def prefix_visibility_analysis(df_sort, exp_n):
    from_time = float(exp.get_experiment_from_time(exp_n))
    to_time = float(exp.get_experiment_to_time(exp_n))

    # First of all we are going to split data per monitor
    aux_monitor_end = 0
    monitor_indexes = get_change_index_per_column(df_sort['MONITOR'], 0, len(df_sort['MONITOR']))

    # Lists to generate result dataframe
    monitors = []
    prefixes = []
    visibilities_per_prefix = []
    updates_per_prefix = []
    ASes = []

    for i, from_i in enumerate(monitor_indexes):
        if i < len(monitor_indexes) - 1:
            to_i = monitor_indexes[i + 1]
        else:
            to_i = len(df_sort['MONITOR'])
        current_monitor = df_sort['MONITOR'][from_i]
        print current_monitor
        prefixes_per_monitor = df_sort['PREFIX'][from_i:to_i]
        times_per_monitor = df_sort['TIME'][from_i:to_i]
        pref_types_per_monitor = df_sort['TYPE'][from_i:to_i]
        AS_per_monitor = df_sort['AS'][from_i:to_i]

        prefix_indexes = get_change_index_per_column(prefixes_per_monitor, from_i, to_i)
        print "df monitor from {} to {}".format(from_i, to_i)
        aux_monitor_end += len(prefixes_per_monitor)
        # Prefixes loop
        for from_j, from_j_df in enumerate(prefix_indexes):
            if from_j < len(prefix_indexes) - 1:
                prefix_window = range(prefix_indexes[from_j], prefix_indexes[from_j + 1])
            else:
                prefix_window = range(prefix_indexes[from_j], aux_monitor_end)

            current_prefix = prefixes_per_monitor[from_j_df]
            current_prefix_AS = AS_per_monitor[from_j_df]
            print current_prefix
            times_per_prefix = times_per_monitor[prefix_window]
            pref_types_per_prefix = pref_types_per_monitor[prefix_window]

            # Get number of updates per prefix
            # Maybe addition of links or AS Prepending
            pref_types_per_prefix_l = pref_types_per_prefix.tolist()

            if pref_types_per_prefix_l.pop(0) == 'B':
                updates_per_prefix.append(len(pref_types_per_prefix_l))
            else:
                updates_per_prefix.append(len(pref_types_per_prefix_l) + 1)

            visibility_per_prefix = get_visibility_time_per_prefix(times_per_prefix, pref_types_per_prefix, from_time,
                                                                   to_time, prefix_window)

            print visibility_per_prefix

            monitors.append(current_monitor)
            prefixes.append(current_prefix)
            visibilities_per_prefix.append(visibility_per_prefix)
            ASes.append(current_prefix_AS)

    return monitors, prefixes, visibilities_per_prefix, updates_per_prefix, ASes


def get_most_specific_mask(covered_prefixes):
    masks = []

    for pref_rnode in covered_prefixes:
        masks.append(pref_rnode.prefixlen)
    sorted_masks = sorted(masks)
    more_specific_mask = sorted_masks[-1]

    return more_specific_mask


def get_results(pref, tree):
    least_specific_rnode = tree.search_worst(pref)
    covered_rnodes = tree.search_covered(pref)

    least_specific_pref = least_specific_rnode.prefix
    most_specifc_mask = get_most_specific_mask(covered_rnodes)
    # Get current prefix length
    pref_len = int(pref.split('/')[1])

    if most_specifc_mask == pref_len and least_specific_pref == pref:
        pref_type = 'unique'
        deep = 0

    elif most_specifc_mask == pref_len and least_specific_pref != pref:
        pref_type = 'more_specific'
        deep = most_specifc_mask - least_specific_rnode.prefixlen
    elif most_specifc_mask != pref_len and least_specific_pref == pref:
        pref_type = 'least_specific'
        deep = 0
    else:
        pref_type = 'more_specific'
        deep = tree.search_exact(pref).prefixlen - least_specific_rnode.prefixlen

    return pref_type, deep


def cluster_more_specifcs(pref, tree):
    least_specific_rnode = tree.search_worst(pref)
    covered_rnodes = tree.search_covered(pref)

    least_specific_pref = least_specific_rnode.prefix
    most_specifc_mask = get_most_specific_mask(covered_rnodes)
    # Get current prefix length
    pref_len = int(pref.split('/')[1])

    if most_specifc_mask == pref_len and least_specific_pref == pref:
        pref_type = 'more_specific - single level'
    elif most_specifc_mask == pref_len and least_specific_pref != pref:
        pref_type = 'more_specific - more_specific'
    elif most_specifc_mask != pref_len and least_specific_pref == pref:
        pref_type = 'more_specific - TOP'
    else:
        pref_type = 'more_specific - more_specific'

    return pref_type


def clustering_prefixes(df_pref_per_monitor):
    # First of all we are going to split data per monitor
    monitor_indexes = get_change_index_per_column(df_pref_per_monitor['MONITOR'], 0,
                                                  len(df_pref_per_monitor['MONITOR']))
    # Lists to store results
    pref_types = []
    deeps = []

    for i, from_i in enumerate(monitor_indexes):
        # Create a new tree per monitor
        rtree = radix.Radix()

        if i < len(monitor_indexes) - 1:
            to_i = monitor_indexes[i + 1]
        else:
            to_i = len(df_pref_per_monitor['MONITOR'])
        current_monitor = df_pref_per_monitor['MONITOR'][from_i]
        print current_monitor
        prefixes_per_monitor = df_pref_per_monitor['PREFIX'][from_i:to_i]

        # Fill tree with prefixes of the current monitor
        for prefix in prefixes_per_monitor:
            rtree.add(prefix)

        # Get results -> pref_type and deep
        if 'TYPE' in df_pref_per_monitor:
            for prefix in prefixes_per_monitor:
                pref_type = cluster_more_specifcs(prefix, rtree)
                pref_types.append(pref_type)
        else:
            for prefix in prefixes_per_monitor:
                pref_type, deep = get_results(prefix, rtree)
                pref_types.append(pref_type)
                deeps.append(deep)

    return pref_types, deeps


def IPv_analysis(IPv_type, exp_n, res_directory, coll, from_d, to_d, ext):
    input_file_path = res_directory + exp_n + '/5.split_data_for_analysis/' + IPv_type + '/' + coll + '_' + from_d + '-' + to_d + ext
    output_file_path = res_directory + exp_n + '/6.more_specifics_analysis/' + IPv_type + '/' + coll + '_' + from_d + '-' + to_d + '.csv'

    write_flag = f.overwrite_file(output_file_path)

    if write_flag:
        print "Loading " + input_file_path + "..."

        df = f.read_file(file_ext, input_file_path)
        df_sort = df.sort_values(by=['MONITOR', 'PREFIX', 'TIME'])
        df_sort = df_sort.reset_index(drop=True)
        df_sort = df_sort.drop(['Unnamed: 0'], axis=1)

        print "Data loaded successfully"

        # 1.Prefix visibility analysis
        print 'Getting visibility per prefix...'
        monitors, prefixes, visibilities_per_prefix, updates_per_prefix, ASes = prefix_visibility_analysis(df_sort,
                                                                                                           exp_n)

        df_prefixes_per_monitor = pd.DataFrame(
            {'MONITOR': monitors, 'PREFIX': prefixes})

        # 2.Clustering prefixes into more specifics, least_specifics and uniques (non-specifics)
        pref_types, deeps = clustering_prefixes(df_prefixes_per_monitor)

        df_visibility_per_prefix = pd.DataFrame(
            {'MONITOR': monitors, 'PREFIX': prefixes, 'VISIBILITY': visibilities_per_prefix,
             'UPDATES': updates_per_prefix, 'TYPE': pref_types,
             'DEEP': deeps, 'ORIGIN': ASes})

        # 3.Clustering more specifics prefixes into TOP, single level and more specifics of other more specifics
        df_more_specifics = df_visibility_per_prefix[df_visibility_per_prefix['TYPE'] == 'more_specific']
        df_more_specifics = df_more_specifics.reset_index(drop=True)
        df_more_specifics = df_more_specifics.drop(['Unnamed: 0'], axis=1)

        pref_types, deeps = clustering_prefixes(df_more_specifics)

        # Replace types for more detailed types
        df_more_specifics['TYPE'] = pref_types

        df_others = df_visibility_per_prefix[df_visibility_per_prefix['TYPE'] != 'more_specific']
        df_others = df_others.reset_index(drop=True)
        df_others = df_others.drop(['Unnamed: 0'], axis=1)

        df_visibility_per_prefix = df_more_specifics.append(df_others, ignore_index=True)

        output_file_path = res_directory + exp_n + '/6.more_specifics_analysis/' + IPv_type + '/' + collector + '_' + from_d + '-' + to_d + '.csv'
        f.save_file(df_visibility_per_prefix, ext, output_file_path)


if __name__ == "__main__":
    print("---------------")
    print("Stage 6: More Specifics Analysis")
    print("---------------")

    # VARIABLES (experiment)
    exp_name, collector = exp.load_arguments()

    experiments = getattr(exp, 'experiments')
    experiment = experiments[exp_name]

    from_date = experiment['initDay']
    to_date = experiment['endDay']
    result_directory = experiment['resultDirectory']
    file_ext = experiment['resultFormat']

    # Directories creation
    step_dir = '/6.more_specifics_analysis'
    exp.per_step_dir(exp_name, step_dir)

    step_dir = '/6.more_specifics_analysis/IPv4/'
    exp.per_step_dir(exp_name, step_dir)

    step_dir = '/6.more_specifics_analysis/IPv6/'
    exp.per_step_dir(exp_name, step_dir)

    # IPv4 analysis
    IPv_analysis('IPv4', exp_name, result_directory, collector, from_date, to_date, file_ext)

    # IPv6 analysis
    IPv_analysis('IPv6', exp_name, result_directory, collector, from_date, to_date, file_ext)
