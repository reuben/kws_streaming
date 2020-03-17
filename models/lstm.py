# coding=utf-8
# Copyright 2020 The Google Research Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""LSTM with Mel spectrum and fully connected layers."""

from kws_streaming.layers import speech_features
from kws_streaming.layers.compat import tf
from kws_streaming.layers.lstm import LSTM
from kws_streaming.layers.stream import Stream
from kws_streaming.models.utils import parse


def model_parameters(parser_nn):
  """LSTM model parameters."""
  parser_nn.add_argument(
      '--lstm_units',
      type=str,
      default='512',
      help='Output space dimensionality of lstm layer ',
  )
  parser_nn.add_argument(
      '--return_sequences',
      type=str,
      default='0',
      help='Whether to return the last output in the output sequence,'
      'or the full sequence',
  )
  parser_nn.add_argument(
      '--stateful',
      type=int,
      default='0',
      help='If True, the last state for each sample at index i'
      'in a batch will be used as initial state for the sample '
      'of index i in the following batch',
  )
  parser_nn.add_argument(
      '--num_proj',
      type=str,
      default='256',
      help='The output dimensionality for the projection matrices.',
  )
  parser_nn.add_argument(
      '--use_peepholes',
      type=int,
      default='1',
      help='True to enable diagonal/peephole connections',
  )
  parser_nn.add_argument(
      '--dropout1',
      type=float,
      default=0.1,
      help='Percentage of data dropped',
  )
  parser_nn.add_argument(
      '--units1',
      type=str,
      default='',
      help='Number of units in the last set of hidden layers',
  )
  parser_nn.add_argument(
      '--act1',
      type=str,
      default='',
      help='Activation function of the last set of hidden layers',
  )


def model(flags):
  """LSTM model.

  Similar model in papers:
  Convolutional Recurrent Neural Networks for Small-Footprint Keyword Spotting
  https://arxiv.org/pdf/1703.05390.pdf (with no conv layer)
  Hello Edge: Keyword Spotting on Microcontrollers
  https://arxiv.org/pdf/1711.07128.pdf

  Args:
    flags: data/model parameters

  Returns:
    Keras model for training
  """
  input_audio = tf.keras.layers.Input(
      shape=(flags.desired_samples,), batch_size=flags.batch_size)

  net = speech_features.SpeechFeatures(
      frame_size_ms=flags.window_size_ms,
      frame_step_ms=flags.window_stride_ms,
      sample_rate=flags.sample_rate,
      use_tf_fft=flags.use_tf_fft,
      preemph=flags.preemph,
      window_type=flags.window_type,
      feature_type=flags.feature_type,
      mel_num_bins=flags.mel_num_bins,
      mel_lower_edge_hertz=flags.mel_lower_edge_hertz,
      mel_upper_edge_hertz=flags.mel_upper_edge_hertz,
      mel_non_zero_only=flags.mel_non_zero_only,
      fft_magnitude_squared=flags.fft_magnitude_squared,
      dct_num_features=flags.dct_num_features)(
          input_audio)

  for units, return_sequences, num_proj in zip(
      parse(flags.lstm_units), parse(flags.return_sequences),
      parse(flags.num_proj)):
    net = LSTM(
        units=units,
        return_sequences=return_sequences,
        stateful=flags.stateful,
        use_peepholes=flags.use_peepholes,
        num_proj=num_proj)(
            net)

  net = Stream(cell=tf.keras.layers.Flatten())(net)
  net = tf.keras.layers.Dropout(rate=flags.dropout1)(net)

  for units, activation in zip(parse(flags.units1), parse(flags.act1)):
    net = tf.keras.layers.Dense(units=units, activation=activation)(net)

  net = tf.keras.layers.Dense(units=flags.label_count)(net)
  return tf.keras.Model(input_audio, net)
