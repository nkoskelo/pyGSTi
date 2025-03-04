"""
Covariance function specialized to the case of a quasistatic DC noise process.
"""
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

from pygsti.modelmembers.covariances.covariancefunc import CovarianceFunction as _CovarianceFunction
from pygsti.modelmembers import ModelMember as _ModelMember
from pygsti.baseobjs.errorgenlabel import ElementaryErrorgenLabel as _ElementaryErrorgenLabel
import numpy as _np

class QuasistaticDCCovarianceFunction(_CovarianceFunction):

    """
    Covariance function based on a quasistatic DC process.
    """

    @classmethod
    def from_errorgen_labels(error_generator_labels):
        pass

    def __init__(self, error_generator_labels):
        """
        Initialize an instance of a quasistatic DC covariance function.
        The covariance function of a quasistatic DC process is given by:

        cov(x_s, x_t) = sigma^2

        Where sigma^2 is the characteristic variance scale for the process.

        Parameters
        ----------
        error_generator_labels : dict
            A nested dictionary whose keys are gate labels and whose values are either a
            dictionary or a list of tuples which specifies the pairs of
            elementary error generators with non-trivial covariances. If a dictionary
            the keys should be tuples containing either one or two error generator labels.
            If length one then this is interpreted to mean the autocorrelation between this error
            with itself at different times. If length two then this is interpreted to be a
            cross-correlation between two different elementary error generators at different times.
            The values of this dictionary are the initial values of
            sigma^2 for this covariance function, respectively.

            If a list of tuples, these tuples have the same format/interpretation as desribed above, but are
            instantiated with t_c and sigma^2 values of zero.    

            #TODO: Add casting logic so that we only need the keys to be castable to error generator labels.

        """

        _ModelMember.__init__(self, None, None)

        #assert that all of the keys/list tuples are error generator labels.
        for cov_spec in error_generator_labels.values():
            for label_tup in cov_spec:
                for lbl in label_tup:
                    assert isinstance(lbl, _ElementaryErrorgenLabel), 'All keys must be `ElementaryErrorgenLabel`s.'

        #initialize some sets for quick gate/error generator lookups when doing calls.
        #self._gate_labels = set()

        #need a mapping between error generator labels and parameter indices
        self._errgen_label_to_param_idx = dict()
        i=0
        for gate_label, cov_spec in error_generator_labels.items():
            if len(gate_label)==1:
                gate_label_tups = [(gate_label[0], gate_label[0])]
            elif len(gate_label)==2:
                gate_label_tups = [(gate_label[0], gate_label[1]), (gate_label[1], gate_label[0])]
            else:
                raise ValueError('Too many gate labels, only correlations between at most 2 gates currently supported.')

            for label_tup in cov_spec:
                if len(label_tup) == 1:
                    for gate_label_tup in gate_label_tups:
                        self._errgen_label_to_param_idx[(gate_label_tup[0], label_tup[0], gate_label_tup[1], label_tup[0])] = i
                elif len(label_tup) == 2:
                    for gate_label_tup in gate_label_tups:
                        self._errgen_label_to_param_idx[(gate_label_tup[0], label_tup[0], gate_label_tup[1], label_tup[1])] = i
                    #also make sure the other direction maps to the same index
                    for gate_label_tup in gate_label_tups:
                        self._errgen_label_to_param_idx[(gate_label_tup[0], label_tup[1], gate_label_tup[1], label_tup[0])] = i
                else:
                    raise ValueError('Too many error generator labels to unpack. Length of tuple of errorgen labels should be either 1 or 2.')
                i+=1
        #allocate arrays to internally store the correlation time and variance scale separately.
        total_num_values = sum([len(lbls_for_gate) for lbls_for_gate in error_generator_labels.values()])
        self.variances = _np.zeros(total_num_values)

        #if a dictionary initialize these values to those values.
        if isinstance(error_generator_labels, dict):
            i=0
            for cov_spec in error_generator_labels.values():
                for var in cov_spec.values():
                    self.variances[i] = var
                    i+=1
        #Concatenate the correlation time and variance vectors.
        self._paramvals = self.variances
        
        #label parameters as either correlation times or variances.
        self._paramlbls = []
        for lbl_tup in self._errgen_label_to_param_idx.keys():
            self._paramlbls.append(f'Covariance for {lbl_tup}')
        self._paramlbls = _np.array(self._paramlbls, dtype=object)      

    def to_vector(self):
        return self._paramvals

    def from_vector(self, v, close=False, dirty_value=True):
        self._paramvals[:] = v
        self.variances = self._paramvals
        self.dirty = dirty_value
    
    #TODO: Add logic for handling different error generator label types.
    #leave the time arguments for API consistency (i.e. so I don't need to branch on the covariance type).
    def __call__(self, errorgen1, gate_label1, time1, errorgen2, gate_label2, time2):
        """
        Computes the correlation function. Takes as input two error generator labels and two times.
        Returns 0 if both error generator labels are not present in this covariance function.
        """
        idx = self._errgen_label_to_param_idx.get((gate_label1, errorgen1, gate_label2, errorgen2), None)

        if idx is None:
            return 0
        else:
            var = self.variances[idx]
            return var

    @property
    def num_params(self):
        """
        Get the number of independent parameters which specify this operation.

        Returns
        -------
        int
            the number of independent parameters.
        """
        return len(self.variances)