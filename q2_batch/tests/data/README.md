# Testing

To test the qiime2 command run
```
qiime batch estimate --i-counts table.qza --m-replicates-file metadata.txt --m-replicates-column reps --m-batches-file metadata.txt --m-batches-column batch --output-dir testing --p-monte-carlo-samples 100 --verbose --p-cores 2
```
