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

"""Tests for kws_streaming.layers.stream."""
import random as rn
from absl.testing import parameterized
import numpy as np
from kws_streaming.layers import stream
from kws_streaming.layers import temporal_padding
from kws_streaming.layers import test_utils
from kws_streaming.layers.compat import tf
from kws_streaming.layers.compat import tf1
from kws_streaming.layers.modes import Modes
from kws_streaming.models import utils
from kws_streaming.train import test
tf1.disable_eager_execution()


# Toy example which require signal processing in time
class Sum(tf.keras.layers.Layer):
  """Applies Sum on time_dim."""

  def __init__(self, time_dim=1, **kwargs):
    super(Sum, self).__init__(**kwargs)
    self.time_dim = time_dim

  def call(self, inputs):
    return tf.keras.backend.sum(inputs, axis=self.time_dim)

  def get_config(self):
    config = {'time_dim': self.time_dim}
    base_config = super(Sum, self).get_config()
    return dict(list(base_config.items()) + list(config.items()))


def conv_model(flags, cnn_filters, cnn_kernel_size, cnn_act, cnn_dilation_rate,
               cnn_strides, cnn_use_bias):
  """Toy example of convolutional model with Stream wrapper.

  It can be used for speech enhancement.
  Args:
      flags: model and data settings
      cnn_filters: list of filters in conv layer
      cnn_kernel_size: list of kernel_size in conv layer
      cnn_act: list of activation functions in conv layer
      cnn_dilation_rate: list of dilation_rate in conv layer
      cnn_strides: list of strides in conv layer
      cnn_use_bias: list of use_bias in conv layer
  Returns:
    Keras model

  Raises:
    ValueError: if any of input list has different length from any other
  """

  if not all(
      len(cnn_filters) == len(l) for l in [
          cnn_filters, cnn_kernel_size, cnn_act, cnn_dilation_rate, cnn_strides,
          cnn_use_bias
      ]):
    raise ValueError('all input lists have to be the same length')

  input_audio = tf.keras.layers.Input(
      shape=(flags.desired_samples,), batch_size=flags.batch_size)
  net = input_audio

  net = tf.keras.backend.expand_dims(net)

  for (filters, kernel_size, activation, dilation_rate, strides,
       use_bias) in zip(cnn_filters, cnn_kernel_size, cnn_act,
                        cnn_dilation_rate, cnn_strides, cnn_use_bias):

    net = stream.Stream(
        cell=tf.keras.layers.Conv1D(
            filters=filters,
            kernel_size=kernel_size,
            activation=activation,
            dilation_rate=dilation_rate,
            strides=strides,
            use_bias=use_bias,
            padding='valid'),
        use_one_step=False,
        pad_time_dim='causal')(net)

  return tf.keras.Model(input_audio, net)


def conv_model_no_stream_wrapper(flags, cnn_filters, cnn_kernel_size, cnn_act,
                                 cnn_dilation_rate, cnn_strides, cnn_use_bias):
  """Toy example of convolutional model.

  It has the same model topology as in conv_model() above, but without
  wrapping conv cell by Stream layer, so that all parameters set manually.
  Args:
      flags: model and data settings
      cnn_filters: list of filters in conv layer
      cnn_kernel_size: list of kernel_size in conv layer
      cnn_act: list of activation functions in conv layer
      cnn_dilation_rate: list of dilation_rate in conv layer
      cnn_strides: list of strides in conv layer
      cnn_use_bias: list of use_bias in conv layer
  Returns:
    Keras model
  """

  if not all(
      len(cnn_filters) == len(l) for l in [
          cnn_filters, cnn_kernel_size, cnn_act, cnn_dilation_rate, cnn_strides,
          cnn_use_bias
      ]):
    raise ValueError('all input lists have to be the same length')

  input_audio = tf.keras.layers.Input(
      shape=(flags.desired_samples,), batch_size=flags.batch_size)
  net = input_audio

  net = tf.keras.backend.expand_dims(net)

  for filters, kernel_size, activation, dilation_rate, strides, use_bias in zip(
      cnn_filters, cnn_kernel_size,
      cnn_act, cnn_dilation_rate,
      cnn_strides, cnn_use_bias):

    ring_buffer_size_in_time_dim = dilation_rate * (kernel_size - 1)
    net = stream.Stream(
        cell=tf.identity,
        ring_buffer_size_in_time_dim=ring_buffer_size_in_time_dim,
        use_one_step=False,
        pad_time_dim=None)(net)

    padding_size = ring_buffer_size_in_time_dim
    net = temporal_padding.TemporalPadding(
        padding='causal', padding_size=padding_size)(
            net)

    net = tf.keras.layers.Conv1D(
        filters=filters,
        kernel_size=kernel_size,
        activation=activation,
        dilation_rate=dilation_rate,
        strides=strides,
        use_bias=use_bias,
        padding='valid')(net)  # padding has to be valid!

  return tf.keras.Model(input_audio, net)


class StreamTest(tf.test.TestCase, parameterized.TestCase):

  def setUp(self):
    super(StreamTest, self).setUp()
    seed = 123
    np.random.seed(seed)
    rn.seed(seed)
    tf.random.set_seed(seed)

  def test_streaming_with_effective_tdim(self):
    time_size = 10
    feature_size = 3
    batch_size = 1

    time_dim = 1  # index of time dimensions
    ring_buffer_size_in_time_dim = 3  # effective size of aperture in time dim

    inputs = tf.keras.layers.Input(
        shape=(time_size, feature_size),
        batch_size=batch_size,
        name='inp_sequence')

    mode = Modes.TRAINING

    # in streaming mode it will create a
    # ring buffer with time dim size ring_buffer_size_in_time_dim
    outputs = stream.Stream(
        cell=Sum(time_dim=time_dim),
        mode=mode,
        ring_buffer_size_in_time_dim=ring_buffer_size_in_time_dim)(inputs)
    model_train = tf.keras.Model(inputs, outputs)
    model_train.summary()

    mode = Modes.STREAM_EXTERNAL_STATE_INFERENCE
    input_tensors = [
        tf.keras.layers.Input(
            shape=(
                1,  # time dim is size 1 in streaming mode
                feature_size,
            ),
            batch_size=batch_size,
            name='inp_stream')
    ]
    # convert non streaming model to streaming one
    model_stream = utils.convert_to_inference_model(model_train,
                                                    input_tensors, mode)
    model_stream.summary()

    # second input tostream model is a state, so we can use its shape
    input_state_np = np.zeros(model_stream.inputs[1].shape, dtype=np.float32)

    # input test data
    non_stream_input = np.random.randint(
        1, 10, size=(batch_size, time_size, feature_size))

    # run streaming inference
    # iterate over time dim sample by sample
    for i in range(input_state_np.shape[1]):
      input_stream_np = np.expand_dims(non_stream_input[0][i], 0)
      input_stream_np = np.expand_dims(input_stream_np, 1)
      input_stream_np = input_stream_np.astype(np.float32)
      output_stream_np, output_state_np = model_stream.predict(
          [input_stream_np, input_state_np])
      input_state_np = output_state_np  # update input state

      # emulate sliding window summation
      target = np.sum(
          non_stream_input[:, max(0, i - ring_buffer_size_in_time_dim):i + 1],
          axis=time_dim)
      self.assertAllEqual(target, output_stream_np)

  @parameterized.parameters('causal', 'same')
  def test_padding(self, padding):
    batch_size = 1
    time_dim = 3
    feature_dim = 3
    kernel_size = 3
    inputs = tf.keras.layers.Input(
        shape=(time_dim, feature_dim), batch_size=batch_size)

    # set it in train mode (in stream mode padding is not applied)
    net = stream.Stream(
        mode=Modes.TRAINING,
        cell=tf.keras.layers.Lambda(lambda x: x),
        ring_buffer_size_in_time_dim=kernel_size,
        pad_time_dim=padding)(inputs)
    model = tf.keras.Model(inputs, net)

    np.random.seed(1)
    input_signal = np.random.rand(batch_size, time_dim, feature_dim)
    outputs = model.predict(input_signal)
    self.assertAllEqual(outputs.shape,
                        [batch_size, time_dim + kernel_size - 1, feature_dim])

  @parameterized.parameters(conv_model, conv_model_no_stream_wrapper)
  def test_stream_strided_convolution(self, get_model):
    # Test streaming convolutional layers with striding, dilation.
    cnn_filters = [1, 1, 1, 1]
    cnn_kernel_size = [3, 3, 3, 3]
    cnn_act = ['linear', 'linear', 'elu', 'elu']
    cnn_dilation_rate = [1, 1, 1, 2]
    cnn_strides = [2, 1, 3, 1]
    cnn_use_bias = [False, False, False, False]

    # prepare input data
    params = test_utils.Params(cnn_strides)
    x = np.arange(params.desired_samples)
    frequency = 2.0
    inp_audio = np.cos((2.0 * np.pi / params.desired_samples) * frequency *
                       x) + np.random.rand(1, params.desired_samples) * 0.5

    # prepare non stream model
    model = get_model(params, cnn_filters, cnn_kernel_size, cnn_act,
                      cnn_dilation_rate, cnn_strides, cnn_use_bias)
    model.summary()

    # prepare streaming model
    model_stream = utils.to_streaming_inference(
        model, params, Modes.STREAM_INTERNAL_STATE_INFERENCE)
    model_stream.summary()

    # run inference
    non_stream_out = model.predict(inp_audio)
    stream_out = test.run_stream_inference(params, model_stream, inp_audio)

    # normalize output data and compare them
    channel = 0
    non_stream_out = non_stream_out[0, :, channel]
    stream_out = stream_out[0, :, channel]

    min_len = min(stream_out.shape[0], non_stream_out.shape[0])
    stream_out = stream_out[0:min_len]
    non_stream_out = non_stream_out[0:min_len]
    self.assertAllEqual(non_stream_out.shape, (42,))
    self.assertAllClose(stream_out, non_stream_out)


if __name__ == '__main__':
  tf.test.main()
