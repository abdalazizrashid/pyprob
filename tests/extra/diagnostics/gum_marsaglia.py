import torch
import math
import os
import shutil

import pyprob
import pyprob.diagnostics
from pyprob import Model, InferenceEngine
from pyprob.distributions import Uniform, Normal


class GaussianWithUnknownMeanMarsaglia(Model):
    def __init__(self, prior_mean=1, prior_stddev=math.sqrt(5), likelihood_stddev=math.sqrt(2), replace=True, *args, **kwargs):
        self.prior_mean = prior_mean
        self.prior_stddev = prior_stddev
        self.likelihood_stddev = likelihood_stddev
        self.replace = replace
        super().__init__('Gaussian with unknown mean (Marsaglia)', *args, **kwargs)

    def marsaglia(self, mean, stddev):
        uniform = Uniform(-1, 1)
        s = 1
        i = 0
        while True:
            x = pyprob.sample(uniform, replace=self.replace)
            y = pyprob.sample(uniform, replace=self.replace)
            s = x*x + y*y
            i += 1
            if float(s) < 1:
                pyprob.tag(x, name='x_accepted')
                pyprob.tag(y, name='y_accepted')
                pyprob.tag(s, name='s_accepted')
                break
            else:
                pyprob.tag(x, name='x_rejected')
                pyprob.tag(y, name='y_rejected')
                pyprob.tag(s, name='s_rejected')
        pyprob.tag(i, name='iterations')
        return mean + stddev * (x * torch.sqrt(-2 * torch.log(s) / s))

    def forward(self):
        mu = self.marsaglia(self.prior_mean, self.prior_stddev)
        likelihood = Normal(mu, self.likelihood_stddev)
        pyprob.tag(mu, name='mu')
        pyprob.observe(likelihood, name='obs0')
        pyprob.observe(likelihood, name='obs1')
        return mu


def produce_results(replace, results_dir):
    num_traces = 100000
    num_ic_training_traces = 1000000

    if os.path.exists(results_dir):
        shutil.rmtree(results_dir)
    pyprob.util.create_path(results_dir, directory=True)

    address_dict_file_name = os.path.join(results_dir, 'address_dict')
    model = GaussianWithUnknownMeanMarsaglia(address_dict_file_name=address_dict_file_name, replace=replace)

    ground_truth_trace = next(model._trace_generator(inference_engine=InferenceEngine.RANDOM_WALK_METROPOLIS_HASTINGS))
    observes = {'obs0': ground_truth_trace.named_variables['obs0'].value, 'obs1': ground_truth_trace.named_variables['obs1'].value}

    # posterior_is_file_name = os.path.join(results_dir, 'posterior_is')
    posterior_is = model.posterior(num_traces, inference_engine=InferenceEngine.IMPORTANCE_SAMPLING, observe=observes)
    proposal_is = posterior_is.unweighted().rename(posterior_is.name.replace('Posterior', 'Proposal'))

    model.learn_inference_network(num_ic_training_traces, observe_embeddings={'obs0': {}, 'obs1': {}}, inference_network=pyprob.InferenceNetwork.LSTM)
    # posterior_ic_file_name = os.path.join(results_dir, 'posterior_ic')
    posterior_ic = model.posterior(num_traces, inference_engine=InferenceEngine.IMPORTANCE_SAMPLING_WITH_INFERENCE_NETWORK, observe=observes)
    proposal_ic = posterior_ic.unweighted().rename(posterior_ic.name.replace('Posterior', 'Proposal'))

    posterior_rmh_file_name = os.path.join(results_dir, 'posterior_rmh')
    posterior_rmh = model.posterior(num_traces, inference_engine=InferenceEngine.RANDOM_WALK_METROPOLIS_HASTINGS, observe=observes)

    posterior_rmh_autocorrelation_file_name = os.path.join(results_dir, 'posterior_rmh_autocorrelation')
    pyprob.diagnostics.autocorrelation(posterior_rmh, n_most_frequent=50, plot=True, plot_show=False, file_name=posterior_rmh_autocorrelation_file_name)

    posterior_rmh_gt_file_name = os.path.join(results_dir, 'posterior_rmh_gt')
    posterior_rmh_gt = model.posterior(num_traces, inference_engine=InferenceEngine.RANDOM_WALK_METROPOLIS_HASTINGS, observe=observes, initial_trace=ground_truth_trace)

    posterior_rmh_gr_file_name = os.path.join(results_dir, 'posterior_rmh_gelman_rubin')
    pyprob.diagnostics.gelman_rubin([posterior_rmh, posterior_rmh_gt], n_most_frequent=None, plot=True, plot_show=False, file_name=posterior_rmh_gr_file_name)

    posterior_rmh_log_prob_file_name = os.path.join(results_dir, 'posterior_rmh_log_prob')
    pyprob.diagnostics.log_prob([posterior_rmh, posterior_rmh_gt], plot=True, plot_show=False, file_name=posterior_rmh_log_prob_file_name)

    pyprob.util.create_path(os.path.join(results_dir, 'addresses'), directory=True)
    pyprob.util.create_path(os.path.join(results_dir, 'addresses_aggregated'), directory=True)
    pyprob.util.create_path(os.path.join(results_dir, 'graph'), directory=True)
    pyprob.util.create_path(os.path.join(results_dir, 'graph_aggregated'), directory=True)

    posterior_is_rmh_addresses_file_name = os.path.join(results_dir, 'addresses/posterior_is_rmh_addresses')
    pyprob.diagnostics.address_histograms([posterior_rmh, proposal_is, posterior_is], plot=True, plot_show=False, ground_truth_trace=ground_truth_trace, use_address_base=False, file_name=posterior_is_rmh_addresses_file_name)

    posterior_is_rmh_addresses_aggregated_file_name = os.path.join(results_dir, 'addresses_aggregated/posterior_is_rmh_addresses_aggregated')
    pyprob.diagnostics.address_histograms([posterior_rmh, proposal_is, posterior_is], plot=True, plot_show=False, ground_truth_trace=ground_truth_trace, use_address_base=True, file_name=posterior_is_rmh_addresses_aggregated_file_name)

    posterior_ic_rmh_addresses_file_name = os.path.join(results_dir, 'addresses/posterior_ic_rmh_addresses')
    pyprob.diagnostics.address_histograms([posterior_rmh, proposal_ic, posterior_ic], plot=True, plot_show=False, ground_truth_trace=ground_truth_trace, use_address_base=False, file_name=posterior_ic_rmh_addresses_file_name)

    posterior_ic_rmh_addresses_aggregated_file_name = os.path.join(results_dir, 'addresses_aggregated/posterior_ic_rmh_addresses_aggregated')
    pyprob.diagnostics.address_histograms([posterior_rmh, proposal_ic, posterior_ic], plot=True, plot_show=False, ground_truth_trace=ground_truth_trace, use_address_base=True, file_name=posterior_ic_rmh_addresses_aggregated_file_name)

    posterior_is_graph_file_name = os.path.join(results_dir, 'graph/posterior_is_graph')
    pyprob.diagnostics.graph(posterior_is, file_name=posterior_is_graph_file_name)

    posterior_is_graph_aggregated_file_name = os.path.join(results_dir, 'graph_aggregated/posterior_is_graph_aggregated')
    pyprob.diagnostics.graph(posterior_is, use_address_base=True, file_name=posterior_is_graph_aggregated_file_name)

    posterior_ic_graph_file_name = os.path.join(results_dir, 'graph/posterior_ic_graph')
    pyprob.diagnostics.graph(posterior_ic, file_name=posterior_ic_graph_file_name)

    posterior_ic_graph_aggregated_file_name = os.path.join(results_dir, 'graph_aggregated/posterior_ic_graph_aggregated')
    pyprob.diagnostics.graph(posterior_ic, use_address_base=True, file_name=posterior_ic_graph_aggregated_file_name)

    posterior_rmh_graph_file_name = os.path.join(results_dir, 'graph/posterior_rmh_graph')
    pyprob.diagnostics.graph(posterior_rmh, file_name=posterior_rmh_graph_file_name)

    posterior_rmh_graph_aggregated_file_name = os.path.join(results_dir, 'graph_aggregated/posterior_rmh_graph_aggregated')
    pyprob.diagnostics.graph(posterior_rmh, use_address_base=True, file_name=posterior_rmh_graph_aggregated_file_name)

    posterior_is.close()
    posterior_ic.close()
    posterior_rmh.close()
    posterior_rmh_gt.close()


if __name__ == '__main__':
    pyprob.seed(1)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    print('Current dir: {}'.format(current_dir))

    results_dir = os.path.join(current_dir, 'gum_marsaglia/replace_true')
    produce_results(replace=True, results_dir=results_dir)

    results_dir = os.path.join(current_dir, 'gum_marsaglia/replace_false')
    produce_results(replace=False, results_dir=results_dir)

    print('Done')
