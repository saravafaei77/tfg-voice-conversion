# Created by albert aparicio on 02/04/17
# coding: utf-8

# This script defines an Sequence-to-Sequence model, using the implemented
# encoders and decoders from TensorFlow

# TODO Document and explain steps

# This import makes Python use 'print' as in Python 3.x
from __future__ import print_function

import argparse
import gzip
import os
import timeit
from datetime import datetime
from sys import version_info

import h5py
import numpy as np
import tensorflow as tf
from ahoproc_tools import error_metrics
from tfglib.seq2seq_normalize import mask_data
from tfglib.utils import init_logger

from seq2seq_dataloader import DataLoader
from seq2seq_tf_model import Seq2Seq

# Conditional imports
if version_info.major > 2:
  import pickle
else:
  import cPickle as pickle

logger, opts = None, None

if __name__ == '__main__':
  # logger.debug('Before parsing args')
  parser = argparse.ArgumentParser(
      description="Convert voice signal with seq2seq model")
  parser.add_argument('--train_data_path', type=str,
                      default="tcstar_data_trim/training/")
  parser.add_argument('--train_out_file', type=str,
                      default="tcstar_data_trim/seq2seq_train_datatable")
  parser.add_argument('--test_data_path', type=str,
                      default="tcstar_data_trim/test/")
  parser.add_argument('--test_out_file', type=str,
                      default="tcstar_data_trim/seq2seq_test_datatable")
  parser.add_argument('--val_fraction', type=float, default=0.25)
  parser.add_argument('--save-h5', dest='save_h5', action='store_true',
                      help='Save dataset to .h5 file')
  parser.add_argument('--max_seq_length', type=int, default=500)
  parser.add_argument('--params_len', type=int, default=44)
  parser.add_argument('--patience', type=int, default=4,
                      help="Patience epochs to do validation, if validation "
                           "score is worse than train for patience epochs "
                           ", quit training. (Def: 4).")
  parser.add_argument('--enc_rnn_layers', type=int, default=1)
  parser.add_argument('--dec_rnn_layers', type=int, default=1)
  parser.add_argument('--rnn_size', type=int, default=512)
  parser.add_argument('--cell_type', type=str, default="lstm")
  parser.add_argument('--batch_size', type=int, default=10)
  parser.add_argument('--epoch', type=int, default=50)
  parser.add_argument('--learning_rate', type=float, default=0.00005)
  parser.add_argument('--dropout', type=float, default=0)
  parser.add_argument('--optimizer', type=str, default="adam")
  parser.add_argument('--clip_norm', type=float, default=5)
  parser.add_argument('--attn_length', type=int, default=500)
  parser.add_argument('--attn_size', type=int, default=256)
  parser.add_argument('--save_every', type=int, default=100)
  parser.add_argument('--no-train', dest='do_train',
                      action='store_false', help='Flag to train or not.')
  parser.add_argument('--no-test', dest='do_test',
                      action='store_false', help='Flag to test or not.')
  parser.add_argument('--save_path', type=str, default="training_results")
  parser.add_argument('--pred_path', type=str, default="tf_predicted")
  parser.add_argument('--tb_path', type=str, default="")
  parser.add_argument('--log', type=str, default="INFO")
  parser.add_argument('--load_model', dest='load_model', action='store_true',
                      help='Load previous model before training')

  parser.set_defaults(do_train=True, do_test=True, save_h5=False,
                      load_model=False)
  opts = parser.parse_args()

  # Initialize logger
  # logger_level = opts.log
  logger = init_logger(name=__name__, level=opts.log)

  logger.debug('Parsed arguments')
  if not os.path.exists(os.path.join(opts.save_path, 'tf_train')):
    os.makedirs(os.path.join(opts.save_path, 'tf_train'))
  # save config
  with gzip.open(os.path.join(opts.save_path, 'tf_train', 'config.pkl.gz'),
                 'wb') as cf:
    pickle.dump(opts, cf)

logger.debug('Before defining main')


def main(args):
  logger.debug('Main')

  # If-else for training and testing
  if args.do_train:
    logger.info('Training')

    logger.debug('Initialize training DataLoader')
    dl = DataLoader(args, logger_level=args.log,
                    max_seq_length=args.max_seq_length)

    logger.debug('Initialize model')
    seq2seq_model = Seq2Seq(args.enc_rnn_layers, args.dec_rnn_layers,
                            args.rnn_size, dl.max_seq_length, args.params_len,
                            batch_size=args.batch_size, logger_level=args.log,
                            dropout=args.dropout,
                            learning_rate=args.learning_rate)

    logger.info('Start training')
    train(seq2seq_model, dl, args)

  if args.do_test:
    tf.reset_default_graph()

    logger.debug('Initialize test DataLoader')
    dl = DataLoader(args, test=True, logger_level=args.log,
                    max_seq_length=args.max_seq_length)

    logger.debug('Initialize model')
    seq2seq_model = Seq2Seq(args.enc_rnn_layers, args.dec_rnn_layers,
                            args.rnn_size, dl.max_seq_length, args.params_len,
                            batch_size=args.batch_size, logger_level=args.log,
                            infer=True, dropout=args.dropout)

    test(seq2seq_model, dl)


logger.debug('Defined main')

logger.debug('Before define evaluate')


def evaluate(sess, model, data_loader, curr_epoch):
  """ Evaluate an epoch over the given data_loader batches """
  batch_idx = 0
  batch_timings = []
  eval_losses = []
  for (
      src_batch, src_batch_seq_len, trg_batch,
      trg_mask) in data_loader.next_batch(
      validation=True):
    # if batch_idx == 0:
    #   batches_per_epoch = data_loader.valid_batches_per_epoch
    beg_t = timeit.default_timer()

    # Model's placeholders
    logger.debug('Fill feed_dict with gtruth and seq_length')
    feed_dict = {
      model.gtruth      : trg_batch[:, :int(model.gtruth.get_shape()[1]), :],
      model.gtruth_masks: trg_mask[:, :int(model.gtruth.get_shape()[1])],
      model.seq_length  : src_batch_seq_len}

    logger.debug('feed_dict - encoder_inputs')
    for i, enc_in in enumerate(model.encoder_inputs):
      # TODO Fix encoder_inputs so that it takes 64 parameters as input
      # feed_dict[enc_in] = src_batch[:,i,:]
      feed_dict[enc_in] = src_batch[:, i, 0:44]

    # Decoder inputs are trg_batch with the first timestep set to 0 (GO)
    logger.debug('Roll decoder inputs and add GO symbol')
    trg_batch = np.roll(trg_batch, 1, axis=1)
    trg_batch[:, 0, :] = np.zeros((model.batch_size, model.parameters_length))

    logger.debug('feed_dict - decoder_inputs')
    for i, dec_in in enumerate(model.decoder_inputs):
      feed_dict[dec_in] = trg_batch[:, i, :]

    eval_losses.append(sess.run(model.val_loss, feed_dict=feed_dict))
    batch_timings.append(timeit.default_timer() - beg_t)

    # print('{}/{} (epoch {}) loss {}, time/batch {} s{}'.format(
    #   batch_idx, valid_batches_per_epoch, curr_epoch, eval_loss,
    #   np.mean(batch_timings), ' ' * 8), end='\r',flush=True)

    if batch_idx >= data_loader.valid_batches_per_epoch:
      break

    batch_idx += 1
    logger.info('** Mean eval loss for epoch {}: {} **'.format(curr_epoch,
                                                               np.mean(
                                                                   eval_losses)))

  return eval_losses


logger.debug('Defined evaluate')

logger.debug('Before define train')


def train(model, dl, args):
  logger.debug('Inside train')
  with tf.Session() as sess:
    if args.load_model:
      # Load model
      model.load(sess, os.path.join(opts.save_path, 'tf_train'))
      logger.info('Loaded model successfully!')
    logger.debug('Define constants')
    batch_idx = 0
    curr_epoch = 0
    count = 0
    batch_timings = []
    tr_losses = []
    val_losses = []

    logger.debug('Initialize TF variables')
    try:
      tf.global_variables_initializer().run()
      merged = tf.summary.merge_all()
    except AttributeError:
      # Backward compatibility
      tf.initialize_all_variables().run()
      merged = tf.merge_all_summaries()

    results_dir = os.path.join(opts.save_path, 'tf_train')
    log_dir = os.path.join(results_dir, 'tensorboard', opts.tb_path)

    if not os.path.exists(log_dir):
      os.makedirs(log_dir)

    train_writer = tf.summary.FileWriter(log_dir, sess.graph)

    best_val_loss = 10e6
    curr_patience = opts.patience
    logger.debug('Defined constants')

    logger.debug('Start batch loop')
    for src_batch, src_batch_seq_len, trg_batch, trg_mask in dl.next_batch():
      if curr_epoch == 0 and batch_idx == 0:
        logger.info('Batches per epoch: {}'.format(dl.train_batches_per_epoch))
        logger.info(
            'Total batches: {}'.format(dl.train_batches_per_epoch * opts.epoch))
      beg_t = timeit.default_timer()

      # Model's placeholders
      logger.debug('Fill feed_dict with gtruth and seq_length')
      feed_dict = {
        model.gtruth      : trg_batch[:, :int(model.gtruth.get_shape()[1]), :],
        model.gtruth_masks: trg_mask[:, :int(model.gtruth.get_shape()[1])],
        model.seq_length  : src_batch_seq_len}

      logger.debug('feed_dict - encoder_inputs')
      for i, enc_in in enumerate(model.encoder_inputs):
        # TODO Fix encoder_inputs so that it takes 64 parameters as input
        # feed_dict[enc_in] = src_batch[:,i,:]
        feed_dict[enc_in] = src_batch[:, i, 0:44]

      # Decoder inputs are trg_batch with the first timestep set to 0 (GO)
      logger.debug('Roll decoder inputs and add GO symbol')
      trg_batch = np.roll(trg_batch, 1, axis=1)
      trg_batch[:, 0, :] = np.zeros((model.batch_size, model.parameters_length))

      logger.debug('feed_dict - decoder_inputs')
      for i, dec_in in enumerate(model.decoder_inputs):
        feed_dict[dec_in] = trg_batch[:, i, :]

      logger.debug('sess.run')
      tr_loss, _, enc_state_fw, summary = sess.run(
          [model.loss, model.train_op, model.enc_state_fw,
           merged],
          feed_dict=feed_dict)

      logger.debug('Append batch timings')
      batch_timings.append(timeit.default_timer() - beg_t)

      # Print batch info
      logger.info(
          'Batch {}/{} (epoch {}) loss {}, time/batch (s) {}\r'.format(
              count,
              opts.epoch * dl.train_batches_per_epoch,  # Total num. of batches
              curr_epoch + 1,
              tr_loss,
              np.mean(
                  batch_timings)))

      tr_losses.append(tr_loss)

      if batch_idx % opts.save_every == 0:
        train_writer.add_summary(summary, count)
        logger.info('Save checkpoint')
        checkpoint_file = os.path.join(results_dir, 'model.ckpt')
        model.save(sess, checkpoint_file, count)
      if batch_idx >= dl.train_batches_per_epoch:
        curr_epoch += 1
        batch_idx = 0

        logger.debug('Evaluate epoch')
        va_loss = np.mean(evaluate(sess, model, dl, curr_epoch))
        val_losses.append(va_loss)

        if va_loss < best_val_loss:
          logger.info(
              'Val loss improved {} --> {}'.format(best_val_loss, va_loss))
          logger.debug('Update the best score')
          best_val_loss = va_loss
          curr_patience = opts.patience
          best_checkpoint_file = os.path.join(results_dir, 'best_model.ckpt')
          model.save(sess, best_checkpoint_file)

          # else:
          #   logger.info(
          #       'Val loss did not improve, patience: {}'.format(
          # curr_patience))
          #
          #   curr_patience -= 1
          #   if model.optimizer == 'sgd':
          #     # if we have SGD optimizer, half the learning rate
          #     curr_lr = sess.run(model.curr_lr)
          #     logger.info(
          #         'Halving lr {} --> {} in SGD'.format(curr_lr,
          # 0.5 * curr_lr))
          #     sess.run(tf.assign(model.curr_lr, curr_lr * .5))
          #   if curr_patience == 0:
          #     logger.info(
          #         'Out of patience ({}) at epoch {} with tr_loss {} and '
          #         'best_val_loss {}'.format(
          #             opts.patience, curr_epoch, tr_loss, best_val_loss))
          #     break

      batch_idx += 1
      count += 1
      if curr_epoch >= opts.epoch:
        logger.info('Finished epochs -> BREAK')
        break

    # Save loss values
    np.savetxt(
        os.path.join(
            results_dir,
            datetime.now().strftime("%Y-%m-%d_%H:%M:%S") + '_tr_losses.csv'),
        tr_losses)
    np.savetxt(
        os.path.join(
            results_dir,
            datetime.now().strftime("%Y-%m-%d_%H:%M:%S") + '_val_losses.csv'),
        val_losses)


logger.debug('Defined train')

logger.debug('Before define test')


def test(model, dl):
  """ Evaluate an epoch over the given data_loader batches """
  # Initialize indexes and constants
  batch_idx = 0
  batch_timings = []
  te_losses = []
  # m_test_loss = None

  # Start TF session
  with tf.Session() as sess:
    # Load model
    if model.load(sess, os.path.join(opts.save_path, 'tf_train')):
      logger.info('Loaded model successfully!')

      n_batch = 0

      # DataLoader.next_batch
      for (src_batch, src_batch_seq_len, trg_batch, trg_mask) in dl.next_batch(
          test=True):

        # TODO Get filename from datatable
        f_name = format(n_batch + 1, '0' + str(
            max(5, len(str(dl.src_test_data.shape[0])))))

        beg_t = timeit.default_timer()

        # Fill feed_dict with test data
        logger.debug('Fill feed_dict with gtruth and seq_length')
        feed_dict = {
          model.gtruth      : trg_batch[:, :int(model.gtruth.get_shape()[1]),
                              :],
          model.gtruth_masks: trg_mask[:, :int(model.gtruth.get_shape()[1])],
          model.seq_length  : src_batch_seq_len}

        logger.debug('feed_dict - encoder_inputs')
        for i, enc_in in enumerate(model.encoder_inputs):
          # TODO Fix encoder_inputs so that it takes 64 parameters as input
          # feed_dict[enc_in] = src_batch[:,i,:]
          feed_dict[enc_in] = src_batch[:, i, 0:44]

        # Decoder inputs are trg_batch with the first timestep set to 0 (GO)
        logger.debug('Roll decoder inputs and add GO symbol')
        trg_batch = np.roll(trg_batch, 1, axis=1)
        trg_batch[:, 0, :] = np.zeros(
            (model.batch_size, model.parameters_length))

        logger.debug('feed_dict - decoder_inputs')
        for i, dec_in in enumerate(model.decoder_inputs):
          feed_dict[dec_in] = trg_batch[:, i, :]

        # sess.run with loss and predictions
        te_loss, predictions = sess.run([model.loss, model.prediction],
                                        feed_dict=feed_dict)
        te_losses.append(te_loss)

        # Append times
        batch_timings.append(timeit.default_timer() - beg_t)

        # Decode predictions
        # predictions.shape -> (batch_size, max_seq_length, params_len)
        # Save original U/V flags to save them to file
        raw_uv_flags = predictions[:, :, 42]

        # Unscale target and predicted parameters
        for i in range(predictions.shape[0]):

          src_spk_index = int(src_batch[i, 0, 44])
          trg_spk_index = int(src_batch[i, 0, 45])

          # Prepare filename
          # Get speakers names
          src_spk_name = dl.s2s_datatable.src_speakers[src_spk_index]
          trg_spk_name = dl.s2s_datatable.trg_speakers[trg_spk_index]

          # Make sure the save directory exists
          tf_pred_path = os.path.join(opts.test_data_path, opts.pred_path)

          if not os.path.exists(
              os.path.join(tf_pred_path, src_spk_name + '-' + trg_spk_name)):
            os.makedirs(
                os.path.join(tf_pred_path, src_spk_name + '-' + trg_spk_name))

            # # TODO Get filename from datatable
            # f_name = format(i + 1, '0' + str(
            # max(5, len(str(dl.src_test_data.shape[0])))))

          with h5py.File(
              os.path.join(tf_pred_path, src_spk_name + '-' + trg_spk_name,
                           f_name + '_' + str(i) + '.h5'), 'w') as file:
            file.create_dataset('predictions', data=predictions[i],
                                compression="gzip",
                                compression_opts=9)
            file.create_dataset('target', data=trg_batch[i],
                                compression="gzip",
                                compression_opts=9)
            file.create_dataset('mask', data=trg_mask[i],
                                compression="gzip",
                                compression_opts=9)

            trg_spk_max = dl.train_trg_speakers_max[trg_spk_index, :]
            trg_spk_min = dl.train_trg_speakers_min[trg_spk_index, :]

            trg_batch[i, :, 0:42] = (trg_batch[i, :, 0:42] * (
              trg_spk_max - trg_spk_min)) + trg_spk_min

            predictions[i, :, 0:42] = (predictions[i, :, 0:42] * (
              trg_spk_min - trg_spk_min)) + trg_spk_min

            # Round U/V flags
            predictions[i, :, 42] = np.round(predictions[i, :, 42])

            # Remove padding in prediction and target parameters
            masked_trg = mask_data(trg_batch[i], trg_mask[i])
            trg_batch[i] = np.ma.filled(masked_trg, fill_value=0.0)
            unmasked_trg = np.ma.compress_rows(masked_trg)

            masked_pred = mask_data(predictions[i], trg_mask[i])
            predictions[i] = np.ma.filled(masked_pred, fill_value=0.0)
            unmasked_prd = np.ma.compress_rows(masked_pred)

            # # Apply U/V flag to lf0 and mvf params
            # unmasked_prd[:, 40][unmasked_prd[:, 42] == 0] = -1e10
            # unmasked_prd[:, 41][unmasked_prd[:, 42] == 0] = 1000

            # Apply ground truth flags to prediction
            unmasked_prd[:, 40][unmasked_trg[:, 42] == 0] = -1e10
            unmasked_prd[:, 41][unmasked_trg[:, 42] == 0] = 1000

            file.create_dataset('unmasked_prd', data=unmasked_prd,
                                compression="gzip",
                                compression_opts=9)
            file.create_dataset('unmasked_trg', data=unmasked_trg,
                                compression="gzip",
                                compression_opts=9)
            file.create_dataset('trg_max', data=trg_spk_max,
                                compression="gzip",
                                compression_opts=9)
            file.create_dataset('trg_min', data=trg_spk_min,
                                compression="gzip",
                                compression_opts=9)
            file.close()

          # Save predictions to files
          np.savetxt(
              os.path.join(tf_pred_path, src_spk_name + '-' + trg_spk_name,
                           f_name + '_' + str(i) + '.vf.dat'),
              unmasked_prd[:, 41]
              )
          np.savetxt(
              os.path.join(tf_pred_path, src_spk_name + '-' + trg_spk_name,
                           f_name + '_' + str(i) + '.lf0.dat'),
              unmasked_prd[:, 40]
              )
          np.savetxt(
              os.path.join(tf_pred_path, src_spk_name + '-' + trg_spk_name,
                           f_name + '_' + str(i) + '.mcp.dat'),
              unmasked_prd[:, 0:40],
              delimiter='\t'
              )
          np.savetxt(
              os.path.join(tf_pred_path, src_spk_name + '-' + trg_spk_name,
                           f_name + '_' + str(i) + '.uv.dat'),
              raw_uv_flags[i, :]
              )

        # Display metrics
        print('Num - {}'.format(n_batch))

        print('MCD = {} dB'.format(
            error_metrics.MCD(unmasked_trg[:, 0:40].reshape(-1, 40),
                              unmasked_prd[:, 0:40].reshape(-1, 40))))
        acc, _, _, _ = error_metrics.AFPR(unmasked_trg[:, 42].reshape(-1, 1),
                                          unmasked_prd[:, 42].reshape(-1, 1))
        print('U/V accuracy = {}'.format(acc))

        pitch_rmse = error_metrics.RMSE(
            np.exp(unmasked_trg[:, 40].reshape(-1, 1)),
            np.exp(unmasked_prd[:, 40].reshape(-1, 1)))
        print('Pitch RMSE = {}'.format(pitch_rmse))

        # Increase batch index
        if batch_idx >= dl.test_batches_per_epoch:
          break
        batch_idx += 1

        n_batch += 1

      # Print test results
      m_test_loss = np.mean(te_losses)
      print('** Mean test loss {} **'.format(m_test_loss))

      # Save loss values
      np.savetxt(
          os.path.join(
              os.path.join(opts.save_path, 'tf_train'),
              datetime.now().strftime("%Y-%m-%d_%H:%M:%S") + '_te_losses.csv'),
          te_losses)

      return m_test_loss


logger.debug('Defined test')

if __name__ == '__main__':
  logger.debug('Before calling main')
  main(opts)
