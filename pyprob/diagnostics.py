import torch
import os
from collections import OrderedDict
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
import time
import sys
import math

from . import __version__, util, PriorInflation, InferenceEngine
from .distributions import Empirical
from .graph import Graph
from .trace import Trace


def network_statistics(inference_network, report_dir=None):
    train_iter_per_sec = inference_network._total_train_iterations / inference_network._total_train_seconds
    train_traces_per_sec = inference_network._total_train_traces / inference_network._total_train_seconds
    train_traces_per_iter = inference_network._total_train_traces / inference_network._total_train_iterations
    train_loss_initial = inference_network._history_train_loss[0]
    train_loss_final = inference_network._history_train_loss[-1]
    train_loss_change = train_loss_final - train_loss_initial
    train_loss_change_per_sec = train_loss_change / inference_network._total_train_seconds
    train_loss_change_per_iter = train_loss_change / inference_network._total_train_iterations
    train_loss_change_per_trace = train_loss_change / inference_network._total_train_traces
    valid_loss_initial = inference_network._history_valid_loss[0]
    valid_loss_final = inference_network._history_valid_loss[-1]
    valid_loss_change = valid_loss_final - valid_loss_initial
    valid_loss_change_per_sec = valid_loss_change / inference_network._total_train_seconds
    valid_loss_change_per_iter = valid_loss_change / inference_network._total_train_iterations
    valid_loss_change_per_trace = valid_loss_change / inference_network._total_train_traces

    stats = OrderedDict()
    stats['pyprob_version'] = __version__
    stats['torch_version'] = torch.__version__
    stats['modified'] = inference_network._modified
    stats['updates'] = inference_network._updates
    stats['trained_on_device'] = str(inference_network._device)
    stats['valid_size'] = inference_network._valid_size
    stats['total_train_seconds'] = inference_network._total_train_seconds
    stats['total_train_traces'] = inference_network._total_train_traces
    stats['total_train_iterations'] = inference_network._total_train_iterations
    stats['train_iter_per_sec'] = train_iter_per_sec
    stats['train_traces_per_sec'] = train_traces_per_sec
    stats['train_traces_per_iter'] = train_traces_per_iter
    stats['train_loss_initial'] = train_loss_initial
    stats['train_loss_final'] = train_loss_final
    stats['train_loss_change_per_sec'] = train_loss_change_per_sec
    stats['train_loss_change_per_iter'] = train_loss_change_per_iter
    stats['train_loss_change_per_trace'] = train_loss_change_per_trace
    stats['valid_loss_initial'] = valid_loss_initial
    stats['valid_loss_final'] = valid_loss_final
    stats['valid_loss_change_per_sec'] = valid_loss_change_per_sec
    stats['valid_loss_change_per_iter'] = valid_loss_change_per_iter
    stats['valid_loss_change_per_trace'] = valid_loss_change_per_trace

    if report_dir is not None:
        if not os.path.exists(report_dir):
            print('Directory does not exist, creating: {}'.format(report_dir))
            os.makedirs(report_dir)
        file_name_stats = os.path.join(report_dir, 'inference_network_stats.txt')
        print('Saving diagnostics information to {} ...'.format(file_name_stats))
        with open(file_name_stats, 'w') as file:
            file.write('pyprob diagnostics report\n')
            for key, value in stats.items():
                file.write('{}: {}\n'.format(key, value))
            file.write('architecture:\n')
            file.write(str(next(inference_network.modules())))

        mpl.rcParams['axes.unicode_minus'] = False
        plt.switch_backend('agg')

        file_name_loss = os.path.join(report_dir, 'loss.pdf')
        print('Plotting loss to file: {} ...'.format(file_name_loss))
        fig = plt.figure(figsize=(10, 7))
        ax = plt.subplot(111)
        ax.plot(inference_network._history_train_loss_trace, inference_network._history_train_loss, label='Training')
        ax.plot(inference_network._history_valid_loss_trace, inference_network._history_valid_loss, label='Validation')
        ax.legend()
        plt.xlabel('Training traces')
        plt.ylabel('Loss')
        plt.grid()
        fig.tight_layout()
        plt.savefig(file_name_loss)

        file_name_num_params = os.path.join(report_dir, 'num_params.pdf')
        print('Plotting number of parameters to file: {} ...'.format(file_name_num_params))
        fig = plt.figure(figsize=(10, 7))
        ax = plt.subplot(111)
        ax.plot(inference_network._history_num_params_trace, inference_network._history_num_params, label='Training')
        plt.xlabel('Training traces')
        plt.ylabel('Number of parameters')
        plt.grid()
        fig.tight_layout()
        plt.savefig(file_name_num_params)

        report_dir_params = os.path.join(report_dir, 'params')
        if not os.path.exists(report_dir_params):
            print('Directory does not exist, creating: {}'.format(report_dir_params))
            os.makedirs(report_dir_params)
        file_name_params = os.path.join(report_dir_params, 'params.csv')
        with open(file_name_params, 'w') as file:
            file.write('file_name, param_name\n')
            for index, param in enumerate(inference_network.named_parameters()):
                file_name_param = os.path.join(report_dir_params, 'param_{}.png'.format(index))
                param_name = param[0]
                file.write('{}, {}\n'.format(os.path.basename(file_name_param), param_name))
                print('Plotting to file: {}  parameter: {} ...'.format(file_name_param, param_name))
                param_val = param[1].detach().numpy()
                if param_val.ndim == 1:
                    param_val = np.expand_dims(param_val, 1)
                if param_val.ndim > 2:
                    print('Cannot render parameter {} because it is {}-dimensional.'.format(param_name, param_val.ndim))
                else:
                    fig = plt.figure(figsize=(10, 7))
                    ax = plt.subplot(111)
                    heatmap = ax.pcolor(param_val, cmap=plt.cm.jet)
                    ax.invert_yaxis()
                    plt.xlabel('{} {}'.format(param_name, param_val.shape))
                    plt.colorbar(heatmap)
                    # fig.tight_layout()
                    plt.savefig(file_name_param)
    return stats


def graph(trace_dist, use_address_base=True, n_most_frequent=None, base_graph=None, report_dir=None, bins=30, log_xscale=False, log_yscale=False):
    stats = OrderedDict()
    stats['pyprob_version'] = __version__
    stats['torch_version'] = torch.__version__
    stats['num_distribution_elements'] = len(trace_dist)

    print('Building graph...')
    if base_graph is not None:
        use_address_base = base_graph.use_address_base
    master_graph = Graph(trace_dist=trace_dist, use_address_base=use_address_base, n_most_frequent=n_most_frequent, base_graph=base_graph)
    address_stats = master_graph.address_stats
    stats['addresses'] = len(address_stats)
    stats['addresses_controlled'] = len([1 for value in list(address_stats.values()) if value['variable'].control])
    stats['addresses_replaced'] = len([1 for value in list(address_stats.values()) if value['variable'].replace])
    stats['addresses_observable'] = len([1 for value in list(address_stats.values()) if value['variable'].observable])
    stats['addresses_observed'] = len([1 for value in list(address_stats.values()) if value['variable'].observed])

    address_ids = [i for i in range(len(address_stats))]
    address_weights = []
    for key, value in address_stats.items():
        address_weights.append(value['count'])
    address_id_dist = Empirical(address_ids, weights=address_weights, name='Address ID')

    trace_stats = master_graph.trace_stats
    trace_ids = [i for i in range(len(trace_stats))]
    trace_weights = []
    for key, value in trace_stats.items():
        trace_weights.append(value['count'])
    trace_id_dist = Empirical(trace_ids, weights=trace_ids, name='Unique trace ID')
    trace_length_dist = trace_dist.map(lambda trace: trace.length).unweighted().rename('Trace length (all)')
    trace_length_controlled_dist = trace_dist.map(lambda trace: trace.length_controlled).unweighted().rename('Trace length (controlled)')
    trace_execution_time_dist = trace_dist.map(lambda trace: trace.execution_time_sec).unweighted().rename('Trace execution time (s)')

    stats['trace_types'] = len(trace_stats)
    stats['trace_length_min'] = float(trace_length_dist.min)
    stats['trace_length_max'] = float(trace_length_dist.max)
    stats['trace_length_mean'] = float(trace_length_dist.mean)
    stats['trace_length_stddev'] = float(trace_length_dist.stddev)
    stats['trace_length_controlled_min'] = float(trace_length_controlled_dist.min)
    stats['trace_length_controlled_max'] = float(trace_length_controlled_dist.max)
    stats['trace_length_controlled_mean'] = float(trace_length_controlled_dist.mean)
    stats['trace_length_controlled_stddev'] = float(trace_length_controlled_dist.stddev)
    stats['trace_execution_time_min'] = float(trace_execution_time_dist.min)
    stats['trace_execution_time_max'] = float(trace_execution_time_dist.max)
    stats['trace_execution_time_mean'] = float(trace_execution_time_dist.mean)
    stats['trace_execution_time_stddev'] = float(trace_execution_time_dist.stddev)

    if report_dir is not None:
        if not os.path.exists(report_dir):
            print('Directory does not exist, creating: {}'.format(report_dir))
            os.makedirs(report_dir)
        file_name_stats = os.path.join(report_dir, 'stats.txt')
        print('Saving diagnostics information to {} ...'.format(file_name_stats))
        with open(file_name_stats, 'w') as file:
            file.write('pyprob diagnostics report\n')
            for key, value in stats.items():
                file.write('{}: {}\n'.format(key, value))

        file_name_addresses = os.path.join(report_dir, 'addresses.csv')
        print('Saving addresses to {} ...'.format(file_name_addresses))
        with open(file_name_addresses, 'w') as file:
            file.write('address_id, weight, name, controlled, replaced, observable, observed, {}\n'.format('address_base' if use_address_base else 'address'))
            for key, value in address_stats.items():
                name = '' if value['variable'].name is None else value['variable'].name
                file.write('{}, {}, {}, {}, {}, {}, {}, {}\n'.format(value['address_id'], value['weight'], name, value['variable'].control, value['variable'].replace, value['variable'].observable, value['variable'].observed, key))

        file_name_traces = os.path.join(report_dir, 'traces.csv')
        print('Saving addresses to {} ...'.format(file_name_traces))
        with open(file_name_traces, 'w') as file:
            file.write('trace_id, weight, length, length_controlled, address_id_sequence\n')
            for key, value in trace_stats.items():
                file.write('{}, {}, {}, {}, {}\n'.format(value['trace_id'], value['weight'], len(value['trace'].variables), len(value['trace'].variables_controlled), ' '.join(value['address_id_sequence'])))

        file_name_address_id_dist = os.path.join(report_dir, 'address_ids.pdf')
        print('Saving trace type distribution to {} ...'.format(file_name_address_id_dist))
        address_id_dist.plot_histogram(bins=range(len(address_stats)), xticks=range(len(address_stats)), log_xscale=log_xscale, log_yscale=log_yscale, color='black', show=False, file_name=file_name_address_id_dist)

        file_name_trace_id_dist = os.path.join(report_dir, 'trace_ids.pdf')
        print('Saving trace type distribution to {} ...'.format(file_name_trace_id_dist))
        trace_id_dist.plot_histogram(bins=range(len(trace_stats)), xticks=range(len(trace_stats)), log_xscale=log_xscale, log_yscale=log_yscale, color='black', show=False, file_name=file_name_trace_id_dist)

        file_name_trace_length_dist = os.path.join(report_dir, 'trace_length_all.pdf')
        print('Saving trace length (all) distribution to {} ...'.format(file_name_trace_length_dist))
        trace_length_dist.plot_histogram(bins=bins, log_xscale=log_xscale, log_yscale=log_yscale, color='black', show=False, file_name=file_name_trace_length_dist)

        file_name_trace_length_controlled_dist = os.path.join(report_dir, 'trace_length_controlled.pdf')
        print('Saving trace length (controlled) distribution to {} ...'.format(file_name_trace_length_controlled_dist))
        trace_length_controlled_dist.plot_histogram(bins=bins, log_xscale=log_xscale, log_yscale=log_yscale, color='black', show=False, file_name=file_name_trace_length_controlled_dist)

        file_name_trace_execution_time_dist = os.path.join(report_dir, 'trace_execution_time.pdf')
        print('Saving trace execution time distribution to {} ...'.format(file_name_trace_execution_time_dist))
        trace_execution_time_dist.plot_histogram(bins=bins, log_xscale=log_xscale, log_yscale=log_yscale, color='black', show=False, file_name=file_name_trace_execution_time_dist)

        report_latent_root = os.path.join(report_dir, 'latent_structure')
        if not os.path.exists(report_latent_root):
            print('Directory does not exist, creating: {}'.format(report_latent_root))
            os.makedirs(report_latent_root)
        file_name_latent_structure_all_pdf = os.path.join(report_latent_root, 'latent_structure_all')
        print('Rendering latent structure graph (all) to {} ...'.format(file_name_latent_structure_all_pdf))
        if base_graph is None:
            master_graph.render_to_file(file_name_latent_structure_all_pdf)
        else:
            master_graph.render_to_file(file_name_latent_structure_all_pdf, background_graph=base_graph)

        for i in range(len(trace_stats)):
            trace_id = list(trace_stats.values())[i]['trace_id']
            file_name_latent_structure = os.path.join(report_latent_root, 'latent_structure_most_freq_{}_{}'.format(i+1, trace_id))
            print('Saving latent structure graph {} of {} to {} ...'.format(i+1, len(trace_stats), file_name_latent_structure))
            graph = master_graph.get_sub_graph(i)
            if base_graph is None:
                graph.render_to_file(file_name_latent_structure, background_graph=master_graph)
            else:
                graph.render_to_file(file_name_latent_structure, background_graph=base_graph)

        print('Rendering distributions...')
        report_distribution_root = os.path.join(report_dir, 'distributions')
        if not os.path.exists(report_distribution_root):
            print('Directory does not exist, creating: {}'.format(report_distribution_root))
            os.makedirs(report_distribution_root)

        i = 0
        for key, value in address_stats.items():
            i += 1
            address_id = value['address_id']
            variable = value['variable']
            can_render = True
            try:
                if use_address_base:
                    address_base = variable.address_base
                    dist = trace_dist.filter(lambda trace: address_base in trace.variables_dict_address_base).map(lambda trace: util.to_tensor(trace.variables_dict_address_base[address_base].value)).filter(lambda v: torch.is_tensor(v)).filter(lambda v: v.nelement() == 1)
                else:
                    address = variable.address
                    dist = trace_dist.filter(lambda trace: address in trace.variables_dict_address).map(lambda trace: util.to_tensor(trace.variables_dict_address[address].value)).filter(lambda v: torch.is_tensor(v)).filter(lambda v: v.nelement() == 1)

                dist.rename(address_id + '' if variable.name is None else '{} (name: {})'.format(address_id, variable.name))
                if dist.length == 0:
                    can_render = False
            except:
                can_render = False

            if can_render:
                file_name_dist = os.path.join(report_distribution_root, '{}_distribution.pdf'.format(address_id))
                print('Saving distribution {} of {} to {} ...'.format(i, len(address_stats), file_name_dist))
                dist.plot_histogram(bins=bins, color='black', show=False, file_name=file_name_dist)
                if not dist._uniform_weights:
                    file_name_dist = os.path.join(report_distribution_root, '{}_{}_distribution.pdf'.format(address_id, 'proposal'))
                    print('Saving distribution {} of {} to {} ...'.format(i, len(address_stats), file_name_dist))
                    dist.unweighted().plot_histogram(bins=bins, color='black', show=False, file_name=file_name_dist)

            else:
                print('Cannot render histogram for {} because it is not scalar valued. Example value: {}'.format(address_id, variable.value))

        file_name_all = os.path.join(report_distribution_root, 'all.pdf')
        print('Combining histograms to: {}'.format(file_name_all))
        status = os.system('pdfjam {}/*.pdf --nup {}x{} --landscape --outfile {}'.format(report_distribution_root, math.ceil(math.sqrt(i)), math.ceil(math.sqrt(i)), file_name_all))
        if status != 0:
            print('Cannot not render to file {}. Check that pdfjam is installed.'.format(file_name_all))

    return master_graph, stats


def log_prob(trace_dists, resolution=1000, names=None, figsize=(10, 5), xlabel="Iteration", ylabel='Log probability', xticks=None, yticks=None, log_xscale=False, log_yscale=False, plot=False, plot_show=True, plot_file_name=None, *args, **kwargs):
    if type(trace_dists) != list:
        raise TypeError('Expecting a list of posterior trace distributions, each from a call to a Model\'s posterior_traces.')
    iters = []
    log_probs = []
    for j in range(len(trace_dists)):
        if type(trace_dists[j][0]) != Trace:
            raise TypeError('Expecting a list of posterior trace distributions, each from a call to a Model\'s posterior_traces.')
        iters.append(list(range(0, trace_dists[j].length, max(1, int(trace_dists[j].length / resolution)))))
        time_start = time.time()
        prev_duration = 0
        num_traces = trace_dists[j].length
        len_str_num_traces = len(str(num_traces))
        print('Loading trace log-probabilities to memory...')
        print('Time spent  | Time remain.| Progress             | {} | Traces/sec'.format('Trace'.ljust(len_str_num_traces * 2 + 1)))
        vals = []
        for i in iters[j]:
            vals.append(trace_dists[j]._get_value(i).log_prob)
            duration = time.time() - time_start
            if (duration - prev_duration > util._print_refresh_rate) or (i == num_traces - 1):
                prev_duration = duration
                traces_per_second = (i + 1) / duration
                print('{} | {} | {} | {}/{} | {:,.2f}       '.format(util.days_hours_mins_secs_str(duration), util.days_hours_mins_secs_str((num_traces - i) / traces_per_second), util.progress_bar(i+1, num_traces), str(i+1).rjust(len_str_num_traces), num_traces, traces_per_second), end='\r')
                sys.stdout.flush()
        print()
        log_probs.append(vals)

    if plot:
        if not plot_show:
            mpl.rcParams['axes.unicode_minus'] = False
            plt.switch_backend('agg')
        fig = plt.figure(figsize=figsize)
        if names is None:
            names = ['{}'.format(trace_dists[i].name) for i in range(len(log_probs))]
        for i in range(len(log_probs)):
            plt.plot(iters[i], log_probs[i], *args, **kwargs, label=names[i])
        if log_xscale:
            plt.xscale('log')
        if log_yscale:
            plt.yscale('log', nonposy='clip')
        if xticks is not None:
            plt.xticks(xticks)
        if yticks is not None:
            plt.xticks(yticks)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.legend(loc='best')
        fig.tight_layout()
        if plot_file_name is not None:
            print('Plotting to file {} ...'.format(plot_file_name))
            plt.savefig(plot_file_name)
        if plot_show:
            plt.show()

    return np.array(iters), np.array(log_probs)


def autocorrelations(trace_dist, names=None, lags=None, n_most_frequent=None, figsize=(10, 5), xlabel="Lag", ylabel='Autocorrelation', xticks=None, yticks=None, log_xscale=True, plot=False, plot_show=True, plot_file_name=None, *args, **kwargs):
    if type(trace_dist) != Empirical:
        raise TypeError('Expecting a posterior trace distribution, from a call to a Model\'s posterior_traces.')
    if type(trace_dist[0]) != Trace:
        raise TypeError('Expecting a posterior trace distribution, from a call to a Model\'s posterior_traces.')

    def autocorrelation(values, lags):
        ret = np.array([1. if lag == 0 else np.corrcoef(values[lag:], values[:-lag])[0][1] for lag in lags])
        # nan is encountered when there is no variance in the values, the foloowing might be used to assign autocorrelation of 1 to such cases
        # ret[np.isnan(ret)] = 1.
        return ret

    if lags is None:
        lags = np.unique(np.logspace(0, np.log10(trace_dist.length/2)).astype(int))
    variable_values = OrderedDict()
    if names is None:
        for name, variable in trace_dist[-1].named_variables.items():
            if not variable.observed and variable.value.nelement() == 1:
                variable_values[(variable.address, name)] = np.zeros(trace_dist.length)
    else:
        for name in names:
            address = trace_dist[-1].named_variables[name].address
            variable_values[(address, name)] = np.zeros(trace_dist.length)

    if n_most_frequent is not None:
        address_counts = {}
        num_traces = trace_dist.length
        util.progress_bar_init('Collecting most frequent addresses...', num_traces)
        for i in range(num_traces):
            util.progress_bar_update(i)
            trace = trace_dist._get_value(i)
            for variable in trace.variables_controlled:
                if variable.value.nelement() == 1:
                    address = variable.address
                    if address not in address_counts:
                        address_counts[address] = 1
                    else:
                        address_counts[address] += 1
        address_counts = {k: v for k, v in address_counts.items() if v >= num_traces}
        address_counts = OrderedDict(sorted(address_counts.items(), key=lambda x: x[1], reverse=True))
        all_variables_count = 0
        for address, count in address_counts.items():
            variable_values[(address, None)] = np.zeros(trace_dist.length)
            all_variables_count += 1
            if all_variables_count == n_most_frequent:
                break
        print()

    if len(variable_values) == 0:
        raise RuntimeError('No variables with scalar value have been selected.')

    variable_values = OrderedDict(sorted(variable_values.items(), reverse=True))

    num_traces = trace_dist.length
    util.progress_bar_init('Loading selected variables to memory...', num_traces)
    for i in range(num_traces):
        trace = trace_dist._get_value(i)
        for (address, name), values in variable_values.items():
            values[i] = float(trace.variables_dict_address[address].value)
        util.progress_bar_update(i)
    print()
    variable_autocorrelations = {}
    i = 0
    for (address, name), values in variable_values.items():
        i += 1
        print('Computing autocorrelation for variable name: {} ({} of {})...'.format(name, i, len(variable_values)))
        variable_autocorrelations[address] = autocorrelation(values, lags)
    if plot:
        if not plot_show:
            mpl.rcParams['axes.unicode_minus'] = False
            plt.switch_backend('agg')
        fig = plt.figure(figsize=figsize)
        plt.axhline(y=0, linewidth=1, color='black')
        other_legend_added = False
        for (address, name), values in variable_values.items():
            if name is None:
                label = None
                if not other_legend_added:
                    label = '{} most frequent addresses'.format(len(variable_values))
                    other_legend_added = True
                plt.plot(lags, variable_autocorrelations[address], *args, **kwargs, linewidth=1, color='gray', label=label)
            else:
                plt.plot(lags, variable_autocorrelations[address], *args, **kwargs, label=name)
        if log_xscale:
            plt.xscale('log')
        if xticks is not None:
            plt.xticks(xticks)
        if yticks is not None:
            plt.xticks(yticks)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.legend(loc='best')
        fig.tight_layout()
        if plot_file_name is not None:
            print('Plotting to file {} ...'.format(plot_file_name))
            plt.savefig(plot_file_name)
        if plot_show:
            plt.show()
    return lags, variable_autocorrelations


def gelman_rubin(trace_dists, names=None, n_most_frequent=None, figsize=(10, 5), xlabel="Iteration", ylabel='R-hat', xticks=None, yticks=None, log_xscale=False, log_yscale=True, plot=False, plot_show=True, plot_file_name=None, *args, **kwargs):
    def merge_dicts(d1, d2):
        for k, v in d2.items():
            if k in d1:
                d1[k] = np.vstack((d1[k], v))
            else:
                d1[k] = v
        return d1

    def gelman_rubin_diagnostic(x, mu=None, logger=None):
        '''
        Notes
        -----
        The diagnostic is computed by:  math:: \hat{R} = \frac{\hat{V}}{W}

        where :math:`W` is the within-chain variance and :math:`\hat{V}` is
        the posterior variance estimate for the pooled traces.

        :param x: samples
        :param mu, var: true posterior mean and variance; if None, Monte Carlo estimates
        :param logger: None
        :return: r_hat

        References
        ----------
        Brooks and Gelman (1998)
        Gelman and Rubin (1992)
        '''
        m, n = x.shape[0], x.shape[1]
        if m < 2:
            raise ValueError(
                'Gelman-Rubin diagnostic requires multiple chains '
                'of the same length.')
        theta = np.mean(x, axis=1)
        sigma = np.var(x, axis=1)
        # theta_m = np.mean(theta, axis=0)
        theta_m = mu if mu else np.mean(theta, axis=0)

        # Calculate between-chain variance
        b = float(n) / float(m-1) * np.sum((theta - theta_m) ** 2)
        # Calculate within-chain variance
        w = 1. / float(m) * np.sum(sigma, axis=0)
        # Estimate of marginal posterior variance
        v_hat = float(n-1) / float(n) * w + float(m+1) / float(m * n) * b
        r_hat = np.sqrt(v_hat / w)
        # logger.info('R: max [%f] min [%f]' % (np.max(r_hat), np.min(r_hat)))
        return r_hat

    def rhat(values, iters):
        ret = np.zeros_like(iters, dtype=float)
        num_missing_samples = trace_dist_length - values.shape[1]
        for i, t in enumerate(iters):
            ret[i] = np.nan if t <= num_missing_samples else gelman_rubin_diagnostic(values[:, :t-num_missing_samples])
        # nan is encountered when there is no variance in the values, the following might be used to assign autocorrelation of 1 to such cases
        # ret[np.isnan(ret)] = 1.
        # nan is also injected when the values length is less than the trace_dist length
        return ret

    def single_trace_dist_values(trace_dist):
        if type(trace_dist) != Empirical:
            raise TypeError('Expecting an MCMC posterior trace distribution, from a call to posterior_traces with an MCMC inference engine.')
        if type(trace_dist[0]) != Trace:
            raise TypeError('Expecting an MCMC posterior trace distribution, from a call to posterior_traces with an MCMC inference engine.')

        variable_values = {}

        num_traces = trace_dist.length
        if num_traces != trace_dist_length:
            raise ValueError('Expecting a list of MCMC posterior trace distributions with the same length.')
        util.progress_bar_init('Loading selected variables to memory...', num_traces)
        for i in range(num_traces):
            trace = trace_dist._get_value(i)
            name_list = trace.named_variables.keys() if names is None else names
            for name in name_list:
                if name not in trace.named_variables:
                    # This random variable is not sampled in the ith trace
                    continue
                variable = trace.named_variables[name]
                if not variable.control and variable.value.nelement() == 1:
                    address = variable.address
                    if (address, name) not in variable_values:
                        # This is the first trace this random variable sample appeared in
                        # Initialize values as a vector of nans. nan means the random variable is not appeared
                        variable_values[(address, name)] = np.ones(trace_dist.length) * np.nan
                    variable_values[(address, name)][i] = float(trace.named_variables[name].value)
            util.progress_bar_update(i)
        print()

        if n_most_frequent is not None:
            address_counts = {}
            num_traces = trace_dist.length
            util.progress_bar_init('Collecting most frequent addresses...', num_traces)
            for i in range(num_traces):
                util.progress_bar_update(i)
                trace = trace_dist._get_value(i)
                for variable in trace.variables_controlled:
                    if variable.value.nelement() == 1:
                        address = variable.address
                        if address not in address_counts:
                            address_counts[address] = 1
                        else:
                            address_counts[address] += 1
            address_counts = {k: v for k, v in address_counts.items() if v >= num_traces}
            address_counts = OrderedDict(sorted(address_counts.items(), key=lambda x: x[1], reverse=True))
            all_variables_count = 0
            for address, count in address_counts.items():
                variable_values[(address, None)] = np.ones(trace_dist.length) * np.nan
                all_variables_count += 1
                if all_variables_count == n_most_frequent:
                    break
            print()
            # TODO: populate values variable_values[(address, name)][i] = float(trace.named_variables[name].value)
            util.progress_bar_init('Collecting most frequent addresses...', num_traces)
            for i in range(num_traces):
                util.progress_bar_update(i)
                trace = trace_dist._get_value(i)
                for (address, name), value in variable_values.items():
                    variable_values[(address, name)][i] = float(trace.variables_dict_address[address].value)
            print()
        variable_values = OrderedDict(sorted(variable_values.items(), reverse=True))
        return variable_values

    variable_values = {}
    trace_dist_length = trace_dists[0].length
    for trace in trace_dists:
        variable_values = merge_dicts(variable_values, single_trace_dist_values(trace))

    iters = np.unique(np.logspace(0, np.log10(trace_dists[-1].length)).astype(int))

    variable_values = {k: v for k, v in variable_values.items() if v.size == trace_dists[0].length * (len(trace_dists))}
    # Fill in the spots where a random variable sample is missing
    # and remove all the values before its first appearance in all chains.
    for (address, name), value in variable_values.items():
        x = np.where(~np.isnan(value)) # Find all nans i.e. missing random variable samples
        r, c = x
        first_non_nans = [np.min(c[r == i]) for i in range(value.shape[0]) if i in r] # For each chain, find the first non-nan value
        starting_col = max(first_non_nans) if first_non_nans else value.shape[1]+1 # Set the starting timestep for all chains
                                                                                   # i.e. the first time it is sampled in all chains
        if starting_col != 0:
            # Remove the initial nans
            value = value[:, starting_col:]
            variable_values[(address, name)] = value

        #assert trace_dists[0].length == value.shape[1] + starting_col
        # Fill in the remaining nans with the last value appeared before them
        for chain_idx in range(len(trace_dists)):
            last_value = value[chain_idx, 0]
            #assert not np.isnan(last_value)
            for i in range(value.shape[1]):
                if np.isnan(value[chain_idx, i]):
                    value[chain_idx, i] = last_value
                last_value = value[chain_idx, i]

    variable_rhats = {}
    i = 0
    for (address, name), values in variable_values.items():
        i += 1
        print('Computing R-hat for named variable {} ({} of {})...'.format(name, i, len(variable_values)))
        variable_rhats[address] = rhat(values, iters)

    if plot:
        if not plot_show:
            mpl.rcParams['axes.unicode_minus'] = False
            plt.switch_backend('agg')
        fig = plt.figure(figsize=figsize)
        plt.axhline(y=1, linewidth=1, color='black')
        other_legend_added = False
        for (address, name), values in variable_values.items():
            if name is None:
                label = None
                if not other_legend_added:
                    label = '{} most frequent addresses'.format(len(variable_values))
                    other_legend_added = True
                plt.plot(iters, variable_rhats[address], *args, **kwargs, linewidth=1, color='gray', label=label)
            else:
                plt.plot(iters, variable_rhats[address], *args, **kwargs, label=name)
        if log_xscale:
            plt.xscale('log')
        if log_yscale:
            plt.yscale('log', nonposy='clip')
        if xticks is not None:
            plt.xticks(xticks)
        if yticks is not None:
            plt.xticks(yticks)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.legend(loc='best')
        fig.tight_layout()
        if plot_file_name is not None:
            print('Plotting to file {} ...'.format(plot_file_name))
            plt.savefig(plot_file_name)
        if plot_show:
            plt.show()

    return iters, variable_rhats


class Diagnostics():
    def __init__(self, model):
        self._model = model

    def inference_network(self, report_dir=None):
        if self._model._inference_network is None:
            raise RuntimeError('The model does not have a trained inference network. Use learn_inference_network first.')
        return network_statistics(self._model._inference_network, report_dir)

    def prior_graph(self, num_traces=1000, prior_inflation=PriorInflation.DISABLED, use_address_base=True, bins=30, log_xscale=False, log_yscale=False, n_most_frequent=None, base_graph=None, report_dir=None, *args, **kwargs):
        trace_dist = self._model.prior_traces(num_traces=num_traces, prior_inflation=prior_inflation, *args, **kwargs)
        if report_dir is not None:
            report_dir = os.path.join(report_dir, 'prior')
            if not os.path.exists(report_dir):
                print('Directory does not exist, creating: {}'.format(report_dir))
                os.makedirs(report_dir)
            file_name_dist = os.path.join(report_dir, 'traces.distribution')
            print('Saving trace distribution to {} ...'.format(file_name_dist))
            trace_dist.save(file_name_dist)
        return graph(trace_dist, use_address_base, n_most_frequent, base_graph, report_dir, bins, log_xscale, log_yscale)

    def posterior_graph(self, num_traces=1000, inference_engine=InferenceEngine.IMPORTANCE_SAMPLING, observe=None, use_address_base=True, bins=100, log_xscale=False, log_yscale=False, n_most_frequent=None, base_graph=None, report_dir=None, *args, **kwargs):
        trace_dist = self._model.posterior_traces(num_traces=num_traces, inference_engine=inference_engine, observe=observe, *args, **kwargs)
        if report_dir is not None:
            report_dir = os.path.join(report_dir, 'posterior/' + inference_engine.name)
            if not os.path.exists(report_dir):
                print('Directory does not exist, creating: {}'.format(report_dir))
                os.makedirs(report_dir)
            file_name_dist = os.path.join(report_dir, 'traces.distribution')
            print('Saving trace distribution to {} ...'.format(file_name_dist))
            trace_dist.save(file_name_dist)
        return graph(trace_dist, use_address_base, n_most_frequent, base_graph, report_dir, bins, log_xscale, log_yscale)
