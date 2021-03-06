import numba
import numpy as np
from numba import jit, njit
from copy import deepcopy
import time

from ...utils.logger import log, LEVEL
from .base import BaseIterativeClustering

import sys


def timeit(function):
    """will time a function's execution time
    Required:
        function -- full namespace for a function
    Optional:
        args -- list of arguments for function
        kwargs -- keyword arguments for function
    """
    def wrapper(*args, **kwargs):
        st = time.time()
        output = function(*args, **kwargs)
        elapsed = str(time.time()-st)[:-4]
        if hasattr(function, 'im_class'):
            fname = '.'.join([function.im_class.__name__, function.__name__])
        else:
            fname = function.__name__
        print('"{0}" Complete - Elapsed time: {2}'.format(fname, sys.modules[function.__module__], elapsed))
        return output
    return wrapper


class SeparateAttributeCategoryPMF(BaseIterativeClustering):

    def _random_swap(self, victim_cluster=-1, prototype_index=-1):

        print('Impurity before random swap: {}'.format(self.clustering.calculate_overall_impurity()))
        # log('Performing random swap...', level=LEVEL.VERBOSE)

        # Choosing the new prototype
        if prototype_index == -1:
            prototype_cluster = np.random.choice(self.n_clusters)
            items = np.where(np.array(self.cluster_assignments) == prototype_cluster)[0]
            while len(items) == 0:
                prototype_cluster = np.random.choice(self.n_clusters)
                items = np.where(np.array(self.cluster_assignments) == prototype_cluster)[0]
            prototype_choice = np.random.choice(len(items))
            prototype_index = items[prototype_choice]
        multi_index = self.multi_indexes[prototype_index]
        prototype_prev_cluster = self.cluster_assignments[prototype_index]

        # log('Chosen data point: ' + ''.join(prototype) + ' in cluster ' + str(prototype_prev_cluster), tabs=1, level=LEVEL.VERBOSE)

        # Choosing a victim cluster to be sacrificed
        if victim_cluster == -1:
            victim_cluster = np.random.choice(self.n_clusters)
            while prototype_prev_cluster == victim_cluster:
                victim_cluster = np.random.choice(self.n_clusters)

        # log('Chosen victim cluster: ' + str(victim_cluster), tabs=1, level=LEVEL.VERBOSE)

        # Creating the new cluster
        new_cluster = np.zeros(self.clustering.clusters[0].shape)
        for dimension, index in enumerate(multi_index):
            new_cluster[dimension, index] += 1

        # Updating the clustering cmfs
        self.clustering.remove_row_from_cluster(multi_index, prototype_prev_cluster)
        self.clustering.clusters[victim_cluster] = new_cluster
        self.clustering.cluster_sizes[victim_cluster] = 1

        # Updating the cluster assignments
        self.cluster_assignments = list(map(lambda x: -1 if x == victim_cluster else x, self.cluster_assignments))
        self.cluster_assignments[prototype_index] = victim_cluster

    @jit
    def _calculate_centroids(self) -> list:

        cluster_matrices = []
        dimensions = list(range(len(self.clustering.n_categories)))
        # log('Calculating centroids...', level=LEVEL.VERBOSE)

        # epsilon_use_count = 0

        for k in range(self.n_clusters):

            # Todo: think about empty clusters

            # log('Cluster: ' + str(k), tabs=1, level=LEVEL.VERBOSE)
            cluster_dimensions = np.zeros(self.clustering.clusters[0].shape)
            cluster_size = self.clustering.clusters[k][0, :].sum()
            if cluster_size == 0:
                print('Cluster size 0!')
                self.should_abort = True
                return None

            for d in dimensions:

                # eps_use = False

                categories_count = len(self.category_counts[d])
                cluster_dimensions[d, :] = deepcopy(self.clustering.clusters[k][d, :] / cluster_size)

                nonzero_indices = cluster_dimensions[d, :categories_count].nonzero()[0]
                empty_categories_count = (categories_count - len(nonzero_indices))
                # min_nonzero_category = dimension_values[nonzero_indices].min()
                # log('Dimension: ' + str(d) + ', Category counts: ' + str(dimension_values), tabs=2, level=LEVEL.VERBOSE)

                if empty_categories_count > 0:
                    # eps_use = True
                    # Todo: epsilon idea is tough! (Choosing epsilon value)
                    # log('Found ' + str(empty_categories_count) + ' empty categories.', tabs=2, level=LEVEL.VERBOSE)
                    # epsilon = min(1.0 / cluster_size, min_nonzero_category / (2 * empty_categories_count))
                    # EPS_PARAM = 2
                    # epsilon = min_nonzero_category / (EPS_PARAM * empty_categories_count)
                    epsilon = 1 / (cluster_size+1)
                    # epsilon = 1 / self.dataset.shape[0]
                    # sum_epsilons = epsilon * empty_categories_count
                    # log('Epsilon: ' + str(epsilon) + ', min_nonzero: ' + str(min_nonzero_category), tabs=2, level=LEVEL.VERBOSE)
                    mask = np.zeros(cluster_dimensions[d, :].shape, dtype=bool)
                    mask[nonzero_indices] = True
                    cluster_dimensions[d, mask] = cluster_dimensions[d, mask] * (1 - epsilon)
                    # dimension_values[mask] = dimension_values[mask] * (1 - sum_epsilons)
                    # dimension_values[mask] = dimension_values[mask] * (cluster_size / (cluster_size + 1))
                    cluster_dimensions[d, ~mask] = epsilon
                    # dimension_values[~mask] = 1 / self.category_counts[d][~mask]
                    cluster_dimensions[d, categories_count:] = 0
                    # cluster_dimensions[d, :categories_count] = np.log()
                    # log('Final dimension ' + str(d) + ': ' + str(dimension_values), tabs=3, level=LEVEL.VERBOSE)

                cluster_dimensions[d, :categories_count] = np.log(cluster_dimensions[d, :categories_count])

                # if eps_use:
                #     epsilon_use_count += 1

            cluster_matrices += [cluster_dimensions]

        # print('Epsilon used ' + str(epsilon_use_count) + ' times')

        return cluster_matrices

    @staticmethod
    @njit
    def _get_sum(data):
        return np.sum(data)

    @staticmethod
    @njit
    def _indexed_get_sum(centroid, indices):
        result = 0
        for i in range(len(indices)):
            result += centroid[indices[i]]
        return result

    @jit(parallel=True)
    def _assign_data_to_clusters(self, centroids: list) -> int:

        # move_in = time.time()
        dims_array = np.arange(self.dataset.shape[1]) * centroids[0].shape[1]

        for k in range(self.n_clusters):
            centroids[k] = centroids[k].ravel()

        # self._reset_combination_decisions()

        movements = 0
        for index in range(self.n_points):

            # last_stop = time.time()
            prev_cluster = self.cluster_assignments[index]
            multi_index = self.multi_indexes[index]
            indices = dims_array + multi_index
            # self.step_calc_1 += time.time() - last_stop
            # last_stop = time.time()

            most_entropy = -1e5
            selected_cluster = -1
            for k in range(self.n_clusters):
                result = self._indexed_get_sum(centroids[k], indices)
                if result > most_entropy:
                    most_entropy = result
                    selected_cluster = k
            # self.step_calc_2 += time.time() - last_stop
            # last_stop = time.time()

            if prev_cluster != selected_cluster:
                if prev_cluster != -1:
                    self.clustering.remove_row_from_cluster(multi_index, prev_cluster)
                self.clustering.assign_row_to_cluster(multi_index, selected_cluster)
                movements += 1
                self.cluster_assignments[index] = selected_cluster

            # self.step_calc_3 += time.time() - last_stop

        # self.overall_time += time.time() - move_in
        return movements
