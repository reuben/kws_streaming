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

"""Wrapper for streaming inference."""
from absl import logging
from kws_streaming.layers.compat import tf
from kws_streaming.layers.modes import Modes


class Stream(tf.keras.layers.Layer):
  """Streaming wrapper - it is not a standalone layer.

  It can be used to wrap Keras layer for streaming inference mode.
  Advantage of streaming inference mode - it is more computationally efficient.
  But not all layers are streamable. Some layers require keeping a buffer
  with features in time. We can wrap such layer by Stream().
  Where Stream() will create and keep a temporal buffer called state,
  for both cases: internal state and external state.
  Examples of layers which require temporal buffer/state
  for streaming inference are Conv2D, DepthwiseConv2D, AveragePooling2D,
  Flatten in time dimension, etc.

  This wrapper is generic enough, so that it can be used for any modes:
  1 Streaming with internal state. This wrapper will manage internal state.
  2 Streaming with external state. Developer will have to manage external state
  and feed it as additional input to the model and then receive output with
  updated state.
  3 Non streaming inference mode. In this case wrapper will just call
  a wrapped layer as it is. There will be no difference in efficiency.
  The graph will be the same as in training mode, but some training features
  will be removed (such as dropout, etc)
  4 Training mode.
  """

  def __init__(self,
               cell,
               inference_batch_size=1,
               mode=Modes.TRAINING,
               pad_time_dim=False,
               state_shape=None,
               **kwargs):
    super(Stream, self).__init__(**kwargs)

    self.cell = cell
    self.inference_batch_size = inference_batch_size
    self.mode = mode
    self.pad_time_dim = pad_time_dim
    self.state_shape = state_shape

    self.effective_ksize_tdim = None
    if (isinstance(cell, tf.keras.layers.Conv2D) or
        isinstance(cell, tf.keras.layers.DepthwiseConv2D)):
      strides = cell.get_config()['strides']
      if self.mode not in (Modes.TRAINING,
                           Modes.NON_STREAM_INFERENCE) and strides[0] > 1:
        raise ValueError('Stride in time dim %d greater than 1 '
                         'in streaming mode not supported' % strides[0])
      dilation_rate = cell.get_config()['dilation_rate']
      kernel_size = cell.get_config()['kernel_size']
      # effective kernel size in time dimension
      self.effective_ksize_tdim = dilation_rate[0] * (kernel_size[0] - 1) + 1

    elif isinstance(self.cell, tf.keras.layers.AveragePooling2D):
      strides = cell.get_config()['strides']
      pool_size = cell.get_config()['pool_size']
      if self.mode not in (Modes.TRAINING, Modes.NON_STREAM_INFERENCE
                          ) and strides[0] != pool_size[0]:
        raise ValueError('Stride in time %d must = pool size in time %d' %
                         (strides[0], pool_size[0]))
      # effective kernel size in time dimension
      self.effective_ksize_tdim = pool_size[0]

    elif isinstance(self.cell, tf.keras.layers.Flatten):
      # effective kernel size in time dimension
      if self.state_shape:
        self.effective_ksize_tdim = self.state_shape[1]

    else:
      raise ValueError('Cell is not supported ', cell)

    if self.effective_ksize_tdim == 1:
      logging.warn('There is no need to use Stream on time dim with size 1')

  def build(self, input_shape):
    super(Stream, self).build(input_shape)
    if isinstance(self.cell, tf.keras.layers.Conv2D) or isinstance(
        self.cell, tf.keras.layers.DepthwiseConv2D) or isinstance(
            self.cell, tf.keras.layers.AveragePooling2D):
      self.state_shape = [self.inference_batch_size, self.effective_ksize_tdim
                         ] + input_shape.as_list()[2:]

    if isinstance(self.cell, tf.keras.layers.Flatten) and not self.state_shape:
      if self.mode in (Modes.TRAINING, Modes.NON_STREAM_INFERENCE):
        # Only in the non-streaming modes we have access to the whole training
        # sequence. In the streaming mode input_shape will not be available.
        # During streaming inference we have access to one sample at a time!
        # So we generate state shape based on input_shape during training.
        # It will be stored in the layer config
        # Then used by clone_streaming_model to create state buffer,
        # during layer initialization.
        # [batch, time, feature, ...]
        self.state_shape = input_shape.as_list()
        self.state_shape[0] = self.inference_batch_size

    if self.mode == Modes.STREAM_INTERNAL_STATE_INFERENCE:
      # Create a state varaible for streaming inference mode (internal state).
      # Where states become a weight in the layer
      self.states = self.add_weight(
          name='states',
          shape=self.state_shape,
          trainable=False,
          initializer=tf.zeros_initializer)

    elif self.mode == Modes.STREAM_EXTERNAL_STATE_INFERENCE:
      # For streaming inference with extrnal states,
      # the states are passed in as input.
      self.input_state = tf.keras.layers.Input(
          shape=self.state_shape[1:],
          batch_size=self.inference_batch_size,
          name=self.name + '/input_state')  # adding names to make it unique
      self.output_state = None

  def call(self, inputs):
    if self.mode == Modes.STREAM_INTERNAL_STATE_INFERENCE:
      return self._streaming_internal_state(inputs)

    elif self.mode == Modes.STREAM_EXTERNAL_STATE_INFERENCE:
      # in streaming inference mode with external state
      # in addition to the output we return the output state.
      output, self.output_state = self._streaming_external_state(
          inputs, self.input_state)
      return output

    elif self.mode in (Modes.TRAINING, Modes.NON_STREAM_INFERENCE):
      # run non streamable training or non streamable inference
      return self._non_streaming(inputs)

    else:
      raise ValueError('wrong mode', self.mode)

  def get_config(self):
    config = super(Stream, self).get_config()
    config.update({
        'inference_batch_size': self.inference_batch_size,
        'mode': self.mode,
        'pad_time_dim': self.pad_time_dim,
        'cell': self.cell,
        'state_shape': self.state_shape,
    })
    return config

  def get_input_state(self):
    # input state will be used only for STREAM_EXTERNAL_STATE_INFERENCE mode
    if self.mode == Modes.STREAM_EXTERNAL_STATE_INFERENCE:
      return self.input_state
    else:
      raise ValueError('wrong mode', self.mode)

  def get_output_state(self):
    # output state will be used only for STREAM_EXTERNAL_STATE_INFERENCE mode
    if self.mode == Modes.STREAM_EXTERNAL_STATE_INFERENCE:
      return self.output_state
    else:
      raise ValueError('wrong mode', self.mode)

  def _streaming_internal_state(self, inputs):
    # The time dimenstion always has to equal 1 in streaming mode.
    if inputs.shape[1] != 1:
      raise ValueError('inputs.shape[1]: %d must be 1 ' % inputs.shape[1])

    # remove latest row [batch_size, (memory_size-1), feature_dim, channel]
    memory = self.states[:, 1:self.effective_ksize_tdim, :]

    # add new row [batch_size, memory_size, feature_dim, channel]
    memory = tf.keras.backend.concatenate([memory, inputs], 1)

    assign_states = self.states.assign(memory)

    with tf.control_dependencies([assign_states]):
      return self.cell(memory)

  def _streaming_external_state(self, inputs, state):
    # The time dimenstion always has to equal 1 in streaming mode.
    if inputs.shape[1] != 1:
      raise ValueError('inputs.shape[1]: %d must be 1 ' % inputs.shape[1])

    # remove latest row [batch_size, (memory_size-1), feature_dim, channel]
    memory = state[:, 1:self.effective_ksize_tdim, :]

    # add new row [batch_size, memory_size, feature_dim, channel]
    memory = tf.keras.backend.concatenate([memory, inputs], 1)

    output = self.cell(memory)
    return output, memory

  def _non_streaming(self, inputs):
    # Zero pad inputs in time dime, from the left to make convolution causal.
    if self.pad_time_dim:
      if isinstance(self.cell, tf.keras.layers.Conv2D) or isinstance(
          self.cell, tf.keras.layers.DepthwiseConv2D):
        inputs = tf.pad(inputs, ((0, 0), (self.effective_ksize_tdim - 1, 0),
                                 (0, 0), (0, 0)), 'constant')
    return self.cell(inputs)
