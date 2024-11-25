"""
The ComposedInstrumentOp class and supporting functionality.
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

import numpy as _np

from pygsti.modelmembers.operations import DenseOperator as _DenseOperator
from pygsti.baseobjs import statespace as _statespace


class ComposedInstrumentOp(_DenseOperator):
    """
    An element of a :class:`ComposedInstrument`.

    A partial implementation of :class:`LinearOperator` which encapsulates an
    element of a :class:`ComposedInstrument`.  Instances rely on their parent being a
    `ComposedInstrument`.

    Parameters
    ----------
    noise_map : ExpErrorgenOp
        The noise map in the auxiliary picture which parameterize *all* of the
        `MCMInstrument`'s elements.

    index : int
        The index indicating which element of the `TPInstrument` the
        constructed object is.  Must be in the range
        `[0,len(param_ops)-1]`.

    basis : Basis or {'pp','gm','std'} or None
        The basis used to construct the Hilbert-Schmidt space representation
        of this state as a super-operator.  If None, certain functionality,
        such as access to Kraus operators, will be unavailable.
        
    right_isometry : numpy array
        The right isometry to be used to map from the auxiliary picture to the submembers. 
        Should be inherited from base `MCMInstrument`.

    left_isometry : list of numpy arrays
        The right isometry to be used to map from the auxiliary picture to the submembers.
        Should be inherited from base `MCMInstrument` and will have same number of elements
        as 'index.' 
    
    """
    def __init__(self, noise_map, index, right_isometry, left_isometry, basis=None):
        self.index = index
        self.noise_map = noise_map 
        dim = int(self.noise_map.dim/4)
        
        self.op_right_iso = right_isometry 
        self.op_left_iso = left_isometry[index] 

        _DenseOperator.__init__(self, _np.identity(dim, 'd'), basis, self.noise_map.evotype,
                                _statespace.default_space_for_dim(dim))
        self._construct_matrix()
        self.init_gpindices()
        
    def _construct_matrix(self):
        self._ptr.flags.writeable = True
        
        self._ptr[:, :] = self.op_left_iso @ self.noise_map.to_dense() @ self.op_right_iso 
    
        assert(self._ptr.shape == (self.dim, self.dim))
        self._ptr.flags.writeable = False
        self._ptr_has_changed()

    def from_vector(self, v, close=False, dirty_value=True):
        """
        Initialize the Instrument using a vector of its parameters.

        Parameters
        ----------
        v : numpy array
            The 1D vector of gate parameters.  Length
            must == num_params().

        close : bool, optional
            Whether `v` is close to this Instrument's current
            set of parameters.  Under some circumstances, when this
            is true this call can be completed more quickly.

        dirty_value : bool, optional
            The value to set this object's "dirty flag" to before exiting this
            call.  This is passed as an argument so it can be updated *recursively*.
            Leave this set to `True` unless you know what you're doing.

        Returns
        -------
        None
        """
        self.noise_map.from_vector(v) 
        self.dirty = dirty_value

    def to_vector(self):  # same as in Instrument but w/.submembers() CONSOLIDATE?
        """
        Extract a vector of the underlying gate parameters from this Instrument.

        Returns
        -------
        numpy array
            a 1D numpy array with length == num_params().
        """
        v = self.noise_map.to_vector()
        return v
        
    def deriv_wrt_params(self, wrt_filter=None):
        """
        The element-wise derivative this operation.

        Construct a matrix whose columns are the vectorized
        derivatives of the flattened operation matrix with respect to a
        single operation parameter.  Thus, each column is of length
        op_dim^2 and there is one column per operation parameter. An
        empty 2D array in the StaticArbitraryOp case (num_params == 0).

        Parameters
        ----------
        wrt_filter : list or numpy.ndarray
            List of parameter indices to take derivative with respect to.
            (None means to use all the this operation's parameters.)

        Returns
        -------
        numpy array
            Array of derivatives with shape (dimension^2, num_params)
        """
        map_dim = self.noise_map.dim 
        noise_map_derivMx = self.noise_map.deriv_wrt_params()
        ptm_wrt_params = []
        for param_num in range(self.noise_map.num_params):
            ptm_noise_map_derivMx = []
            for matrix_el in range(map_dim*map_dim):
                ptm_noise_map_derivMx += [noise_map_derivMx[matrix_el][param_num]]
            ptm_wrt_params += [list(_np.ravel(self.op_left_iso @ _np.reshape(ptm_noise_map_derivMx, (map_dim,map_dim)) @ self.op_right_iso))]
        derivMx = _np.array(ptm_wrt_params).transpose()
        if wrt_filter is None:
            return derivMx
        else:
            return _np.take(derivMx, wrt_filter, axis=1)

    @property
    def num_params(self):
        """
        Get the number of independent parameters which specify this operation.

        Returns
        -------
        int
            the number of independent parameters.
        """
        return len(self.gpindices_as_array())

    def submembers(self):
        """
        Get the ModelMember-derived objects contained in this one.

        Returns
        -------
        list
        """
        return [self.noise_map]