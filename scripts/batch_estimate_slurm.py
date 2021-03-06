import qiime2
import argparse
from dask_jobqueue import SLURMCluster
from dask.distributed import Client
import dask
import dask.dataframe as dd
import dask.array as da
from biom import load_table
import pandas as pd
import numpy as np
import xarray as xr
from q2_batch._batch import _batch_func
import time
import logging
logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.DEBUG)

parser = argparse.ArgumentParser()
parser.add_argument(
    '--biom-table', help='Biom table of counts.', required=True)
parser.add_argument(
    '--metadata-file', help='Sample metadata file.', required=True)
parser.add_argument(
    '--batches', help='Column specifying batches.', required=True)
parser.add_argument(
    '--replicates', help='Column specifying replicates.', required=True)
parser.add_argument(
    '--monte-carlo-samples', help='Number of monte carlo samples.',
    type=int, required=False, default=1000)
parser.add_argument(
    '--cores', help='Number of cores per process.', type=int, required=False, default=1)
parser.add_argument(
    '--processes', help='Number of processes per node.', type=int, required=False, default=1)
parser.add_argument(
    '--nodes', help='Number of nodes.', type=int, required=False, default=1)
parser.add_argument(
    '--memory', help='Memory allocation size.', type=str, required=False, default='16GB')
parser.add_argument(
    '--walltime', help='Walltime.', type=str, required=False, default='01:00:00')
parser.add_argument(
    '--interface', help='Interface for communication', type=str, required=False, default='eth0')
parser.add_argument(
    '--queue', help='Queue to submit job to.', type=str, required=True)
parser.add_argument(
    '--output-tensor', help='Output tensor.', type=str, required=True)

args = parser.parse_args()
print(args)
cluster = SLURMCluster(cores=args.cores,
                       processes=args.processes,
                       memory=args.memory,
                       walltime=args.walltime,
                       interface=args.interface,
                       nanny=True,
                       death_timeout='15s',
                       local_directory='/tmp',
                       shebang='#!/usr/bin/env bash',
                       env_extra=["export TBB_CXX_TYPE=gcc"],
                       queue=args.queue)
print(cluster.job_script())
cluster.scale(jobs=args.nodes)
client = Client(cluster)
print(client)
client.wait_for_workers(args.nodes)
time.sleep(15)
print(cluster.scheduler.workers)
table = load_table(args.biom_table)
counts = pd.DataFrame(np.array(table.matrix_data.todense()).T,
                      index=table.ids(),
                      columns=table.ids(axis='observation'))
metadata = pd.read_table(args.metadata_file, index_col=0)
replicates = metadata[args.replicates]
batches = metadata[args.batches]
# match everything up
idx = list(set(counts.index) & set(replicates.index) & set(batches.index))
counts, replicates, batches = [x.loc[idx] for x in
                               (counts, replicates, batches)]
replicates, batches = replicates.values, batches.values
depth = counts.sum(axis=1)
pfunc = lambda x: _batch_func(x, replicates, batches,
                              depth, args.monte_carlo_samples, chains=1)
dcounts = da.from_array(counts.values.T, chunks=(counts.T.shape))
print('Dimensions', counts.shape, dcounts.shape, len(counts.columns))

res = []
for d in range(dcounts.shape[0]):
    r = dask.delayed(pfunc)(dcounts[d])
    res.append(r)
print('Res length', len(res))
futures = dask.persist(*res)
resdf = dask.compute(futures)
data_df = list(resdf[0])
samples = xr.concat([df.to_xarray() for df in data_df], dim="features")
samples = samples.assign_coords(coords={
    'features' : table.ids(axis='observation'),
    'monte_carlo_samples' : np.arange(args.monte_carlo_samples)})
samples.to_netcdf(args.output_tensor)
