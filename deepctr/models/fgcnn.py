# -*- coding:utf-8 -*-
"""

Author:
    Weichen Shen,wcshen1994@163.com

Reference:
    [1] Liu B, Tang R, Chen Y, et al. Feature Generation by Convolutional Neural Network for Click-Through Rate Prediction[J]. arXiv preprint arXiv:1904.04447, 2019.
    (https://arxiv.org/pdf/1904.04447)

"""
import tensorflow as tf

from ..input_embedding import create_singlefeat_inputdict, create_varlenfeat_inputdict, get_linear_logit
from ..input_embedding import get_inputs_embedding
from ..layers.core import PredictionLayer, MLP
from ..layers.interaction import InnerProductLayer
from ..layers.utils import concat_fun
from ..utils import check_feature_config_dict


def preprocess_input_embedding(feature_dim_dict, embedding_size, l2_reg_embedding, l2_reg_linear, init_std, seed,
                               return_linear_logit=True, ):
    sparse_input_dict, dense_input_dict = create_singlefeat_inputdict(
        feature_dim_dict)
    sequence_input_dict, sequence_pooling_dict, sequence_input_len_dict, sequence_max_len_dict = create_varlenfeat_inputdict(
        feature_dim_dict)
    inputs_list, deep_emb_list, linear_emb_list = get_inputs_embedding(feature_dim_dict, embedding_size,
                                                                       l2_reg_embedding, l2_reg_linear, init_std, seed,
                                                                       sparse_input_dict, dense_input_dict,
                                                                       sequence_input_dict, sequence_input_len_dict,
                                                                       sequence_max_len_dict, sequence_pooling_dict,
                                                                       return_linear_logit, '')
    _, fg_deep_emb_list, _ = get_inputs_embedding(feature_dim_dict, embedding_size,
                                                  l2_reg_embedding, l2_reg_linear, init_std, seed,
                                                  sparse_input_dict, dense_input_dict,
                                                  sequence_input_dict, sequence_input_len_dict,
                                                  sequence_max_len_dict, sequence_pooling_dict, False, prefix='fg')
    if return_linear_logit:
        linear_logit = get_linear_logit(
            linear_emb_list, dense_input_dict, l2_reg_linear)
    else:
        linear_logit = None
    return deep_emb_list, fg_deep_emb_list, linear_logit, inputs_list


def unstack(input):
    input_ = tf.expand_dims(input, axis=2)
    return tf.unstack(input_, input_.shape[1], 1)


def FGCNN(feature_dim_dict, embedding_size=8, conv_kernel_width=(6, 5), conv_filters=(4, 4), new_maps=(3, 3),
          pooling_width=2, hidden_size=(128,)
          , l2_reg_embedding=1e-5, l2_reg_deep=0, keep_prob=1.0, init_std=0.0001, seed=1024,
          final_activation='sigmoid', ):
    """Instantiates the Feature Generation by Convolutional Neural Network architecture.

    :param feature_dim_dict: dict,to indicate sparse field and dense field like {'sparse':{'field_1':4,'field_2':3,'field_3':2},'dense':['field_4','field_5']}
    :param embedding_size: positive integer,sparse feature embedding_size
    :param conv_kernel_width: list,list of positive integer or empty list,the width of filter in each conv layer.
    :param conv_filters: list,list of positive integer or empty list,the number of filters in each conv layer.
    :param new_maps: list, list of positive integer or empty list, the feature maps of generated features.
    :param pooling_width: the width of pooling layer.
    :param hidden_size: list,list of positive integer or empty list, the layer number and units in each layer of deep net.
    :param l2_reg_embedding: float. L2 regularizer strength applied to embedding vector
    :param l2_reg_deep: float. L2 regularizer strength applied to deep net
    :param keep_prob: float in (0,1]. keep_prob after attention net
    :param init_std: float,to use as the initialize std of embedding vector
    :param seed: integer ,to use as random seed.
    :param final_activation: str,output activation,usually ``'sigmoid'`` or ``'linear'``
    :return: A Keras model instance.
    """

    check_feature_config_dict(feature_dim_dict)
    if not (len(conv_kernel_width) == len(conv_filters) == len(new_maps)):
        raise ValueError("conv_kernel_width,conv_filters and new_maps must have same length")

    deep_emb_list, fg_deep_emb_list, linear_logit, inputs_list = preprocess_input_embedding(feature_dim_dict,
                                                                                            embedding_size,
                                                                                            l2_reg_embedding,
                                                                                            0, init_std,
                                                                                            seed, True)
    l = len(conv_filters)
    fg_input = concat_fun(fg_deep_emb_list, axis=1)
    origin_input = concat_fun(deep_emb_list, axis=1)
    pooling_result = tf.keras.layers.Lambda(lambda x: tf.expand_dims(x, axis=3))(fg_input)

    new_feature_list = []

    for i in range(1, l + 1):
        filters = conv_filters[i - 1]
        width = conv_kernel_width[i - 1]
        new_filters = new_maps[i - 1]
        conv_result = tf.keras.layers.Conv2D(filters=filters, kernel_size=(width, 1), strides=(1, 1), padding='same',
                                             activation='tanh', use_bias=True, )(pooling_result)
        pooling_result = tf.keras.layers.MaxPooling2D(pool_size=(pooling_width, 1))(conv_result)
        flatten_result = tf.keras.layers.Flatten()(pooling_result)
        new_result = tf.keras.layers.Dense(pooling_result.shape[1].value * embedding_size * new_filters,
                                           activation='tanh', use_bias=True)(flatten_result)
        new_feature_list.append(
            tf.keras.layers.Reshape((pooling_result.shape[1].value * new_filters, embedding_size))(new_result))
    new_features = concat_fun(new_feature_list, axis=1)
    combined_input = concat_fun([origin_input, new_features], axis=1)

    inner_product = tf.keras.layers.Flatten()(InnerProductLayer()(
        tf.keras.layers.Lambda(unstack, mask=[None] * combined_input.shape[1].value)(combined_input)))
    linear_signal = tf.keras.layers.Flatten()(combined_input)
    dnn_input = tf.keras.layers.Concatenate()([linear_signal, inner_product])
    dnn_input = tf.keras.layers.Flatten()(dnn_input)

    final_logit = MLP(hidden_size, keep_prob=keep_prob, l2_reg=l2_reg_deep)(dnn_input)
    final_logit = tf.keras.layers.Dense(1, use_bias=False)(final_logit)
    output = PredictionLayer(final_activation)(final_logit)

    model = tf.keras.models.Model(inputs=inputs_list, outputs=output)
    return model
