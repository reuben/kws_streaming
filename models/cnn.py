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

"""CNN model with Mel spectrum."""
from kws_streaming.layers import speech_features
from kws_streaming.layers.compat import tf
from kws_streaming.layers.stream import Stream
from kws_streaming.models.utils import parse


def model_parameters(parser_nn):
  """Covolutional Neural Network(CNN) model parameters."""

  parser_nn.add_argument(
      '--cnn_filters',
      type=str,
      default='64,64,64,64,64,64,128',
      help='Number of output filters in the convolution layers',
  )
  parser_nn.add_argument(
      '--cnn_kernel_size',
      type=str,
      default='(3,3),(5,3),(5,3),(5,3),(5,2),(5,1),(5,1)',
      help='Heights and widths of the 2D convolution window',
  )
  parser_nn.add_argument(
      '--cnn_act',
      type=str,
      default="'relu','selu','selu','selu','selu','selu','selu'",
      help='Activation function in the convolution layers',
  )
  parser_nn.add_argument(
      '--cnn_dilation_rate',
      type=str,
      default='(1,1),(1,1),(2,1),(1,1),(2,1),(1,1),(2,1)',
      help='Dilation rate to use for dilated convolutions',
  )
  parser_nn.add_argument(
      '--cnn_strides',
      type=str,
      default='(1,1),(1,1),(1,1),(1,1),(1,1),(1,1),(1,1)',
      help='Strides of the convolution layers along the height and width',
  )
  parser_nn.add_argument(
      '--dropout1',
      type=float,
      default=0.5,
      help='Percentage of data dropped',
  )
  parser_nn.add_argument(
      '--units2',
      type=str,
      default='128,256',
      help='Number of units in the last set of hidden layers',
  )
  parser_nn.add_argument(
      '--act2',
      type=str,
      default="'linear','selu'",
      help='Activation function of the last set of hidden layers',
  )


def model(flags):
  """CNN model.

  It is based on paper:
  Convolutional Neural Networks for Small-footprint Keyword Spotting
  http://www.isca-speech.org/archive/interspeech_2015/papers/i15_1478.pdf

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

  net = tf.keras.backend.expand_dims(net)
  for filters, kernel_size, activation, dilation_rate, strides in zip(
      parse(flags.cnn_filters), parse(flags.cnn_kernel_size),
      parse(flags.cnn_act), parse(flags.cnn_dilation_rate),
      parse(flags.cnn_strides)):
    net = Stream(
        cell=tf.keras.layers.Conv2D(
            filters=filters,
            kernel_size=kernel_size,
            activation=activation,
            dilation_rate=dilation_rate,
            strides=strides))(
                net)

  net = Stream(cell=tf.keras.layers.Flatten())(net)
  net = tf.keras.layers.Dropout(rate=flags.dropout1)(net)

  for units, activation in zip(parse(flags.units2), parse(flags.act2)):
    net = tf.keras.layers.Dense(units=units, activation=activation)(net)

  net = tf.keras.layers.Dense(units=flags.label_count)(net)
  return tf.keras.Model(input_audio, net)
