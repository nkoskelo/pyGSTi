"""
Defines the ParityCheckInst class
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

import collections as _collections
import numpy as _np
from pygsti.modelmembers import modelmember as _mm
from pygsti.modelmembers import operations as _op
from pygsti.baseobjs import statespace as _statespace
from pygsti.tools import matrixtools as _mt
from pygsti.baseobjs.label import Label as _Label
from pygsti.report import reportables as _rp
from pygsti.tools import optools as _ot


class ParityCheckInst(_mm.ModelMember, _collections.OrderedDict):
    """
    A new class for representing a quantum instrument, the mathematical description 
    of an intermediate measurement. This class relies on the "auxiliary picture" where 
    a n-qubit m-outcome intermediate measurement corresponds to a circuit diagram with
    n plus m auxiliary qubits. 

    Using this picture allows us to extract error generators corresponding to the circuit
    diagram and lays the ground work for a CPTPLND parameterization. 

    Parameters
    ----------
    member_ops : dict of LinearOperator objects
        A dict (or list of key,value pairs) of the gates.
    evotype : Evotype or str, optional
        The evolution type.  If `None`, the evotype is inferred
        from the first instrument member.  If `len(member_ops) == 0` in this case,
        an error is raised.

    state_space : StateSpace, optional
        The state space for this POVM.  If `None`, the space is inferred
        from the first instrument member.  If `len(member_ops) == 0` in this case,
        an error is raised.

    items : list or dict, optional
        Initial values.  This should only be used internally in de-serialization.
    """
 
    def __init__(self, evotype="default", state_space=None, items=None, parameterization="CPTPLND"):
        self.parameterization = parameterization

        #Calculate some necessary matrices to define the isometries below 
        zero = 1/_np.sqrt(2) * _np.array([[1],[0],[0],[1]])
        one = 1/_np.sqrt(2) * _np.array([[1],[0],[0],[-1]])
        CNOT = _ot.unitary_to_pauligate(_np.array([[1,0,0,0], [0,1,0,0],[0,0,0,1],[0,0,1,0]]))
        
        dim = 16
        self.aux_GATES = _np.kron(CNOT, _np.identity(4)) @ _np.kron(_np.identity(4), CNOT) @ _np.kron(CNOT, _np.identity(4))
        
        #Define the error generator as the all ones string
        self.error_gen = _op.LindbladErrorgen.from_error_generator(_np.zeros((dim*4,dim*4)), parameterization=self.parameterization) 
        
        if state_space is None: 
            state_space = _statespace.default_space_for_dim(dim)

        #Define the isometries that convert from auxiliary to standard picture 
        self.left_isometry = [_np.kron(_np.identity(dim), zero.T), _np.kron(_np.identity(dim),  one.T)]
        self.right_isometry = self.aux_GATES @ _np.kron(_np.identity(dim), zero)

        #Create the ordered dictionary structure characteristic of instruments 
        items = []
        self.noise_map = _op.ExpErrorgenOp(self.error_gen)
        for i in range(2): 
            items.append([f'p{i}', _op.StaticArbitraryOp(self.left_isometry[i] @ self.noise_map.to_dense() @ self.right_isometry)])

        #some necessary initialization 
        _collections.OrderedDict.__init__(self, items)
        _mm.ModelMember.__init__(self, state_space, evotype)
        self.init_gpindices()
        self._paramlbls = self.error_gen._paramlbls

    def to_vector(self): 
        """
        Gives the underlying vector of parameters. 

        Returns
        -------
        numpy array
            a 1D numpy array with length == num_params().
        """
        return self.error_gen.to_vector()
        
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
        self.error_gen.from_vector(v)
        self.noise_map = _op.ExpErrorgenOp(self.error_gen)
        for i in range(2): 
            self[f'p{i}'] = _op.StaticArbitraryOp(self.left_isometry[i] @ self.noise_map.to_dense() @ self.right_isometry)
        self.dirty = dirty_value 

    @property
    def num_params(self):
        """
        Get the number of independent parameters which specify this Instrument.

        Returns
        -------
        int
            the number of independent parameters.
        """
        return self.error_gen.num_params

    def simplify_operations(self, prefix=""):
        """
        Creates a dictionary of simplified instrument operations.

        Returns a dictionary of operations that belong to the Instrument's parent
        `Model` - that is, whose `gpindices` are set to all or a subset of
        this instruments's gpindices.  These are used internally within
        computations involving the parent `Model`.

        Parameters
        ----------
        prefix : str
            A string, usually identitying this instrument, which may be used
            to prefix the simplified gate keys.

        Returns
        -------
        OrderedDict of Gates
        """
        #Create a "simplified" (Model-referencing) set of element gates
        simplified = _collections.OrderedDict()
        if isinstance(prefix, _Label):  # Deal with case when prefix isn't just a string
            for k, g in self.items():
                simplified[_Label(prefix.name + "_" + k, prefix.sslbls)] = g
        else:
            if prefix: prefix += "_"
            for k, g in self.items():
                simplified[prefix + k] = g
        return simplified

    @property
    def parameter_labels(self): 
        """
        Get the labels of the independent parameters which specify this instrument. 
    
        Returns
        -------
        array
            array of parameter labels 
        """
        return self.error_gen.parameter_labels

    @property
    def num_elements(self):
        """
        Return the number of total gate elements in this instrument.

        This is in general different from the number of *parameters*,
        which are the number of free variables used to generate all of
        the matrix *elements*.

        Returns
        -------
        int
        """
        return sum([g.size for g in self.values()])

    def transform_inplace(self,s): 
        """
        Update each Instrument element matrix `O` with `inv(s) * O * s`
        and update the error generator/noise map appropriately.  

        Parameters
        ----------
        s : GaugeGroupElement
            A gauge group element which specifies the "s" matrix
            (and it's inverse) used in the above similarity transform.

        Returns
        -------
        None
        """
        Smx = s.transform_matrix
        Si = s.transform_matrix_inverse
        self.noise_map = _op.FullTPOp(_np.kron(Si, _np.eye(4)) @ self.noise_map.to_dense() @ self.aux_GATES @ _np.kron(Smx, _np.eye(4))  @ self.aux_GATES)
        self.error_gen = _op.LindbladErrorgen.from_operation_matrix(self.noise_map, parameterization=self.parameterization)
        for i in range(2): 
            self[f'p{i}'] = _op.StaticArbitraryOp(self.left_isometry[i] @ self.noise_map.to_dense() @ self.right_isometry)
        self.dirty = True
    
    def __str__(self):
            s = f'ParityCheckInstrument representing a two-qubit parity check with elements:\n'
            for lbl, element in self.items():
                s += "%s:\n%s\n" % (lbl, _mt.mx_to_string(element.to_dense(), width=4, prec=3))
            return s