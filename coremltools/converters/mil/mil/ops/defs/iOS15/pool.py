#  Copyright (c) 2020, Apple Inc. All rights reserved.
#
#  Use of this source code is governed by a BSD-3-clause license that can be
#  found in the LICENSE.txt file or at https://opensource.org/licenses/BSD-3-Clause

from coremltools.converters.mil.mil import Operation, types
from coremltools.converters.mil.mil.block import curr_opset_version
from coremltools.converters.mil.mil.input_type import (DefaultInputs,
                                                       InputSpec,
                                                       TensorInputType)
from coremltools.converters.mil.mil.ops.defs._op_reqs import register_op
from coremltools.converters.mil.mil.ops.defs._utils import \
    spatial_dimensions_out_shape
from coremltools.converters.mil.mil.ops.defs.iOS15 import _IOS15_TARGET


class Pooling(Operation):
    """
    Pooling Op Superclass
    """
    input_spec = InputSpec(
        x=TensorInputType(type_domain="T"),
        kernel_sizes=TensorInputType(const=True, type_domain=types.int32),
        strides=TensorInputType(const=True, optional=True, type_domain=types.int32),
        pad_type=TensorInputType(const=True, type_domain=types.str),
        pad=TensorInputType(const=True, optional=True, type_domain=types.int32),
        ceil_mode=TensorInputType(const=True, optional=True, type_domain=types.bool),
    )

    type_domains = {
        "T": (types.fp16, types.fp32),
    }

    def default_inputs(self):
        num_spatial_dims = self.x.rank - 2
        return DefaultInputs(
            strides=[1] * num_spatial_dims,
            pad=[0] * 2 * num_spatial_dims,
            ceil_mode=False,
        )

    def type_inference(self):
        ksize = self.kernel_sizes.val
        x_shape = self.x.shape
        D_in_rank = len(x_shape) - 2

        strides = [1] * D_in_rank if self.strides is None else self.strides.val
        pad_type = "valid" if self.pad_type is None else self.pad_type.val.lower()
        if pad_type not in ["valid", "same", "custom", "same_lower"]:
            raise ValueError("Unrecognized value of pad_type : {}".format(pad_type))
        pad = None if self.pad is None else self.pad.val
        D_in = x_shape[2:]  # spatial dimensions

        if self.ceil_mode.val:
            if D_in_rank > 2:
                raise ValueError('pool: ceil_mode only supported for 1D or 2D pool')
            if pad_type == "same" and self.ceil_mode.val:
                raise ValueError("ceil_mode must be False when pad_type==same")
            if pad is not None:
                for i in range(D_in_rank):
                    if pad[2 * i] != pad[2 * i + 1]:
                        raise ValueError("Padding must be symmetric if ceil_mode is True")

        # The same_lower padding is not supported in iOS15
        if curr_opset_version() == _IOS15_TARGET and self.pad_type.val == "same_lower":
            msg = "iOS15 version of pooling layers do not support pad_type = `same_lower`"
            raise ValueError(msg)

        D_out_shape = spatial_dimensions_out_shape(
            pad_type=pad_type,
            input_shape=D_in,
            kernel_shape=ksize,
            strides=strides,
            custom_pad=pad,
            ceil_mode=self.ceil_mode.val,
        )
        ret_shape = list(x_shape[:2]) + D_out_shape
        return types.tensor(self.x.dtype, tuple(ret_shape))


@register_op
class avg_pool(Pooling):
    """
    Perform average pooling. Supports 1-D, 2-D, and 3-D pool (1, 2, or 3 spatial dimensions).

    Parameters
    ----------
    x: tensor<[n,C_in, \\*D_in], T> (Required)
        *  ``3 <= rank <= 5``.
        *  ``D_in`` are spatial dimensions, ``1 <= len(D_in) <= 3``.
        *  ``C_in`` is the number of input channels or depth dimensions.
        *  ``n`` is the batch dimension.

    kernel_sizes: const tensor<[K], T> (Required)
        * The size of the window for each spatial dimension ``D_in`` of the
          input tensor.
        * ``K == len(D_in)``

    strides: const tensor<[S],i32> (Optional, default to all 1s)
        * Stride along each of the spatial dimensions.
        * ``S == len(D_in)``.

    pad_type: const str (Required)
        Must be one of ``valid``, ``same``, ``custom`` or ``same_lower``.

        * ``valid``: No padding. This is equivalent to custom pad with ``pad[i] = 0, for
          all i``.
        * ``same`` : This is equivalent to custom pad with ``pad[2*i] + pad[2*i+1] = kernel_size[i]``.
        * ``custom``: Specify custom padding in the parameter pad. note that ``same``
          padding is equivalent to custom padding with
          ``pad[2*i] + pad[2*i+1] = kernel_size[i]``.
        * ``same_lower``: Similar to ``same`` but the padding
          will place extra rows/cols on the top/left if the padding amount is odd.

    pad: const<[P],i32> (Optional. Default to all 0s)
        * ``pad`` represents the number of elements to pad before and after each
          dimension: ``pad[2*i], pad[2*i+1]`` are the pad size before and after spatial
          dimension ``i``.
        * ``P = 2 * len(D_in)``.
        * ``pad`` should be specified if and only if ``pad_type == custom``

    exclude_padding_from_average: const tensor<[], bool> (Optional, default to False)
        * If ``True``, padded values (0s) are excluded from the denominator count
          when computing the average over the kernel window.

    ceil_mode: const<bool>
        * Same as PyTorch's ``ceil`` mode.
        * ``ceil`` is used instead of floor in calculating the output size.
        * Optional, defaults to ``False``.
        * Only applicable when ``pad_type`` is ``valid`` or ``custom``.
        * When ``ceil_mode`` is True, padding must be symmetric; that is, if specified,
          ``pad[2*i] == pad[2*i+1]`` must hold.

    Returns
    -------
    tensor<[n, C_out, \\*D_out], T>
        * Same rank as ``x``.
        * ``C_out`` is the number of output channels or depth dimensions.
        * When ``ceil_mode = False``:
            * ``D_out[i] = floor[(D_in[i] + pad[2*i] + pad[2*i+1] - kernel_sizes[i]) /
              strides[i]] +1, for i = 0, .., len(D_in) - 1`` is mathematically the same
              as (when all parameters involved are integers):

                  * ``D_out[i] = ceil [(D_in[i] + pad[2*i] + pad[2*i+1] - kernel_size[i] - 1) / stride[i]], for i = 0, .., len(D_in) - 1``.
                  * ``*D_out`` is all ones if ``global_pooling`` is ``true``.

        * When ``ceil_mode = True``:
            * ``D_out[i] = ceil[(D_in[i] + pad[2*i] + pad[2*i+1] - kernel_sizes[i]) / strides[i]] +1, for i = 0, .., len(D_in) - 1``

                  * If  ``(D_out[i] - 1) * strides[i] >= D_in[i] + pad[2*i] and (pad[2*i] + pad[2*i+1] > 0)``
                    then ``D_out[i] = D_out[i] - 1``.

            * The first equation is same as:

                * ``D_out[i] = floor[(D_in[i] + pad[2*i] + pad[2*i+1] - kernel_sizes[i] + strides[i] - 1) / strides[i]] +1, for i = 0, .., len(D_in) - 1``

    Attributes
    ----------
    T: fp16, fp32

    See Also
    --------
    l2_pool, max_pool
    """

    input_spec = (
        InputSpec(
            exclude_padding_from_average=TensorInputType(
                const=True, optional=True, type_domain=types.bool
            )
        )
        + Pooling.input_spec
    )

    def default_inputs(self):
        return super().default_inputs() + DefaultInputs(
            exclude_padding_from_average=False,
        )


@register_op
class l2_pool(Pooling):
    """
    Perform L2 pooling. Supports 1-D and 2-D pool.

    Parameters
    ----------
    x: tensor<[n,C_in,*D_in], T> (Required)
        * Only support 1d and 2d pooling.
        * See :py:class:`avg_pool`.

    kernel_sizes: const tensor<[K], T> (Required)
        * See :py:class:`avg_pool`.

    strides: const tensor<[S],i32> (Optional, default to all 1s)
        * See :py:class:`avg_pool`.

    pad_type: const str (Required)
        * See :py:class:`avg_pool`.

    pad: const<[P],i32> (Optional, default to all 0s)
        * See :py:class:`avg_pool`.

    Returns
    -------
    tensor<[n, C_out,*D_out], T>
        * See :py:class:`avg_pool`.

    Attributes
    ----------
    T: fp16, fp32

    See Also
    --------
    avg_pool, max_pool
    """

    def type_inference(self):
        if self.x.rank - 2 > 2:
            msg = "l2_pool only supports rank 1 or 2. Got rank: {}".format(self.x.rank - 2)
            raise ValueError(msg)
        return super().type_inference()


@register_op
class max_pool(Pooling):
    """
    Perform max pooling. Supports 1-D, 2-D, and 3-D pool.

    Parameters
    ----------
    x: tensor<[n,C_in,*D_in], T> (Required)
        * See :py:class:`avg_pool`.

    kernel_sizes: const tensor<[K], T> (Required)
        * See :py:class:`avg_pool`.

    strides: const tensor<[S],i32> (Optional, default to all 1s)
        * See :py:class:`avg_pool`.

    pad_type: const str (Required)
        * See :py:class:`avg_pool`.

    pad: const<[P],i32> (Optional, default to all 0s)
        * See :py:class:`avg_pool`.

    ceil_mode: const<bool>
        * see :py:class:`avg_pool`.

    Returns
    -------
    tensor<[n, C_out,*D_out], T>
        * See :py:class:`avg_pool`.

    Attributes
    ----------
    T: fp16, fp32

    See Also
    --------
    avg_pool, l2_pool
    """

    pass
