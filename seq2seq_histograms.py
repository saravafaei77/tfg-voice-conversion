# Created by albert aparicio on 12/12/16
# coding: utf-8

# This script computes histograms of predicted parameters to assess the
# performance of the model's training

# This import makes Python use 'print' as in Python 3.x
from __future__ import print_function

import h5py
import matplotlib.pyplot as plt
import numpy as np
import tfglib.seq2seq_datatable as s2s
import tfglib.seq2seq_normalize as s2s_norm
from keras.layers import GRU, Dropout
from keras.layers.core import RepeatVector
from keras.models import Sequential
from keras.optimizers import Adam
from keras.utils.generic_utils import Progbar

#######################
# Sizes and constants #
#######################
nb_sequences = 32

######################
# Load test database #
######################
print('Loading test datatable...', end='')
(src_test_datatable,
 src_test_masks,
 trg_test_datatable,
 trg_test_masks,
 max_test_length,
 test_speakers_max,
 test_speakers_min
 ) = s2s.seq2seq2_load_datatable(
    'data/seq2seq_test_datatable.h5'
)
print('done')

#############################
# Load model and parameters #
#############################
with h5py.File('training_results/seq2seq_training_params.h5', 'r') as f:
    epochs = f.attrs.get('epochs')
    learning_rate = f.attrs.get('learning_rate')
    optimizer = f.attrs.get('optimizer')
    loss = f.attrs.get('loss')
    train_speakers_max = f.attrs.get('train_speakers_max')
    train_speakers_min = f.attrs.get('train_speakers_min')

print('Re-initializing model')
seq2seq_model = Sequential()

# Encoder Layer
seq2seq_model.add(GRU(100,
                      input_dim=44 + 10 + 10,
                      return_sequences=False,
                      consume_less='gpu'
                      ))
seq2seq_model.add(RepeatVector(max_test_length))

# Decoder layer
seq2seq_model.add(GRU(100, return_sequences=True, consume_less='gpu'))
seq2seq_model.add(Dropout(0.5))
seq2seq_model.add(GRU(
    44,
    return_sequences=True,
    consume_less='gpu',
    activation='linear'
))

adam = Adam(clipnorm=10)
seq2seq_model.compile(loss=loss.decode('utf-8'), optimizer=adam,
                      sample_weight_mode="temporal")
seq2seq_model.load_weights('models/seq2seq_' + loss.decode('utf-8') + '_' +
                           optimizer.decode('utf-8') + '_epochs_' +
                           str(epochs) + '_lr_' + str(learning_rate) +
                           '_weights.h5')

##############################
# Predict sequences in batch #
##############################
# Pre-allocate prediction results
predictions = np.zeros(
    (nb_sequences, trg_test_datatable.shape[1], trg_test_datatable.shape[2]))

for i in range(nb_sequences):
    # Normalize sequence
    src_test_datatable[i, :, 0:42] = s2s_norm.maxmin_scaling(
        src_test_datatable[i, :, :],
        src_test_masks[i, :],
        trg_test_datatable[i, :, :],
        trg_test_masks[i, :],
        train_speakers_max,
        train_speakers_min
    )[0]

    # Mask sequence
    masked_sequence = s2s_norm.mask_data(
        src_test_datatable[i, :, :],
        src_test_masks[i, :]
    )

    # Get only valid data
    valid_sequence = masked_sequence[~masked_sequence.mask].reshape(
        (1,
         -1,
         masked_sequence.shape[1])
    )
    # Predict parameters
    prediction = seq2seq_model.predict(valid_sequence)

    # Unscale parameters
    prediction[:, :, 0:42] = s2s_norm.unscale_prediction(
        src_test_datatable[i, :, :],
        src_test_masks[i, :],
        prediction[:, :, 0:42].reshape(-1, 42),
        train_speakers_max,
        train_speakers_min
    )

    # Reshape prediction into 2D matrix
    prediction = prediction.reshape(-1, 44)

    # Round u/v flags #
    prediction[:, 42] = np.round(prediction[:, 42])

    # Apply u/v flags to lf0 and mvf #
    for index, entry in enumerate(prediction[:, 42]):
        if entry == 0:
            prediction[index, 40] = -1e+10  # lf0
            prediction[index, 41] = 0  # mvf

    # Save prediction
    predictions[i] = prediction

###################
# Plot histograms #
###################
print('Computing prediction histograms...')
progress_bar = Progbar(target=trg_test_datatable.shape[2])

progress_bar.update(0)
# Predictions histograms
for param_index in range(trg_test_datatable.shape[2]):
    # Compute histogram
    hist, bins = np.histogram(predictions[:, :, param_index], bins=20)
    width = 0.7 * (bins[1] - bins[0])
    center = (bins[:-1] + bins[1:]) / 2
    plt.bar(center, hist, align='center', width=width)

    # Plot vertical line at mean
    mean = np.mean(predictions[:, :, param_index])
    plt.plot((mean, mean), (0, 1.1 * np.max(hist)), 'r', linewidth=2)

    # Save histogram
    plt.savefig('training_results/hist/seq2seq_' + loss.decode('utf-8') + '_' +
                optimizer.decode('utf-8') + '_epochs_' + str(epochs) + '_lr_' +
                str(learning_rate) + '_pred_param_' + str(
        param_index) + '_hist.png',
                bbox_inches='tight')
    plt.close()

    progress_bar.update(param_index + 1)

print('\n' + 'Computing ground truth histograms...')
progress_bar = Progbar(target=trg_test_datatable.shape[2])

progress_bar.update(0)
# Groundtruth histograms
for param_index in range(trg_test_datatable.shape[2]):
    # Compute histogram
    hist, bins = np.histogram(trg_test_datatable[:, :, param_index], bins=20)
    width = 0.7 * (bins[1] - bins[0])
    center = (bins[:-1] + bins[1:]) / 2
    plt.bar(center, hist, align='center', width=width)

    # Plot vertical line at mean
    mean = np.mean(trg_test_datatable[:, :, param_index])
    plt.plot((mean, mean), (0, 1.1 * np.max(hist)), 'r', linewidth=2)

    # Save histogram
    plt.savefig('training_results/hist/seq2seq_' + loss.decode('utf-8') + '_' +
                optimizer.decode('utf-8') + '_epochs_' + str(epochs) + '_lr_' +
                str(learning_rate) + '_gtrth_param_' + str(
        param_index) + '_hist.png',
                bbox_inches='tight')
    plt.close()

    progress_bar.update(param_index + 1)

print('\n' + '========================' +
      '\n' + '======= FINISHED =======' +
      '\n' + '========================')

exit()
