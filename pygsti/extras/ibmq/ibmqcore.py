""" Functions for sending experiments to IBMQ devices and converting the results to pyGSTi objects """
#***************************************************************************************************
# Copyright 2015, 2019 National Technology & Engineering Solutions of Sandia, LLC (NTESS).
# Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights
# in this software.
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License.  You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0 or in the LICENSE file in the root pyGSTi directory.
#***************************************************************************************************

from ... import data as _data
from ...protocols import ProtocolData as _ProtocolData
import numpy as _np
import time as _time
import json as _json
import pickle as _pickle
import os as _os
import warnings as _warnings
import datetime as _datetime

try: 
    import qiskit as _qiskit
    from qiskit.circuit.library import XGate
    from qiskit.transpiler import PassManager
    from qiskit.transpiler.passes import ALAPScheduleAnalysis, PadDynamicalDecoupling
except: _qiskit = None

try: 
    from qiskit_ibm_runtime import SamplerV2 as Sampler
    from qiskit_ibm_runtime import Session 
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
except: Sampler = None

def insert_dd(circ, backend):
        durations = _qiskit.transpiler.InstructionDurations.from_backend(backend)
	#print(durations)
        pa = backend.configuration().timing_constraints['pulse_alignment']
        # balanced X-X sequence on all qubits
        dd_sequence = [XGate(), XGate()]
        pm = PassManager([ALAPScheduleAnalysis(durations),PadDynamicalDecoupling(durations, dd_sequence, pulse_alignment=pa)])
        circ_dd = pm.run(circ)
        return circ_dd

def add_dd_to_exp(exp, backend):
    for i, batch in enumerate(exp['qiskit_QuantumCircuits']):
        circuits = []
        for qiskit_circ in batch:
            circ_dd = insert_dd(qiskit_circ, backend)
            circuits.append(circ_dd)
        exp['qiskit_DD_QuantumCircuits'][i] = circuits
    return exp

# Most recent version of QisKit that this has been tested on:
#qiskit.__qiskit_version__ = {
#    'qiskit-terra': '0.25.3',
#    'qiskit': '0.44.3',
#    'qiskit-aer': None,
#    'qiskit-ignis': None,
#    'qiskit-ibmq-provider': '0.20.2',
#    'qiskit-nature': None,
#    'qiskit-finance': None,
#    'qiskit-optimization': None,
#    'qiskit-machine-learning': None
#}
#qiskit_ibm_provider.__version__ = '0.7.2'

_attribute_to_json = ['remove_duplicates', 'randomized_order', 'circuits_per_batch', 'num_shots', 'job_ids']
_attribute_to_pickle = ['pspec', 'pygsti_circuits', 'pygsti_openqasm_circuits',
                        'qiskit_QuantumCircuits', 'qiskit_QuantumCircuits_as_openqasm',
                        'submit_time_calibration_data', 'qobj', 'batch_result_object'
                        ]

_attribute_to_pickle_runtime = ['pspec', 'pygsti_circuits', 'pygsti_openqasm_circuits',
                        'qiskit_QuantumCircuits',
                        'submit_time_calibration_data', 'qobj', 'batch_result_object'
                        ]


def reverse_dict_key_bits(counts_dict):
    new_dict = {}
    for key in counts_dict.keys():
        new_dict[key[::-1]] = counts_dict[key]
    return new_dict

def to_labeled_counts(input_dict, ordered_target_indices, num_qubits_in_pspec): 
    outcome_labels = []
    counts_data = []
    for bitstring, count in input_dict.items():
        new_label = []
        term_string = ''
        term_bits = bitstring[:num_qubits_in_pspec][::-1]
        mid_bits = bitstring[num_qubits_in_pspec:][::-1]
        for index in ordered_target_indices:
            term_string += term_bits[index]
        for bit in mid_bits:
            new_label.append('p'+bit)
        new_label.append(term_string)
        outcome_labels.append(tuple(new_label))
        counts_data.append(count)
    return outcome_labels, counts_data

def q_list_to_ordered_target_indices(q_list, num_qubits):
    if q_list is None:
        return list(range(num_qubits))
    else:
        output = []
        for q in q_list:
            assert q[0] == 'Q'
            output.append(int(q[1:]))
        return output


class IBMQExperiment(dict):

    def __init__(self, edesign, pspec, ancilla_label=None,remove_duplicates=True, randomized_order=True, seed=None, circuits_per_batch=75,
                 num_shots=1024, parallel_DD = False, backend=None):
        """
        A object that converts pyGSTi ExperimentDesigns into jobs to be submitted to IBM Q, submits these
        jobs to IBM Q and receives the results.

        Parameters
        ----------
        edesign: ExperimentDesign
            The ExperimentDesign to be run on IBM Q. This can be a combined experiment design (e.g., a GST
            design combined with an RB design).

        pspec: QubitProcessorSpec
            A QubitProcessorSpec that represents the IBM Q device being used. This can be created using the
            extras.devices.create_processor_spec(). The ProcessorSpecs qubit ordering *must* correspond
            to that of the IBM device (which will be the case if you create it using that function).
            I.e., pspecs qubits should be labelled Q0 through Qn-1 and the labelling of the qubits
            should agree with IBM's labelling.

        remove_duplicates: bool, optional
            If true, each distinct circuit in `edesign` is run only once. If false, if a circuit is
            repeated multiple times in `edesign` it is run multiple times.

        randomized_order: bool, optional
            Whether or not to randomize the order of the circuits in `edesign` before turning them
            into jobs to be submitted to IBM Q.

        seed: int or None, optional
            Seed to be used in randomization. 

        circuits_per_batch: int, optional
            The circuits in edesign are divded into batches, each containing at most this many
            circuits. The default value of 75 is (or was) the maximal value allowed on the public
            IBM Q devices.

        num_shots: int, optional
            The number of samples from / repeats of each circuit.

        Returns
        -------
        IBMQExperiment
            An object containing jobs to be submitted to IBM Q, which can then be submitted
            using the methods .submit() and whose results can be grabbed from IBM Q using
            the method .retrieve_results(). This object has dictionary-like access for all of
            the objects it contains (e.g., ['qobj'] is a list of the objects to be submitted to
            IBM Q).

        """

        self['edesign'] = edesign
        self['pspec'] = pspec
        self['remove_duplicates'] = remove_duplicates
        self['randomized_order'] = randomized_order
        self['seed'] = seed #Changed this 
        self['circuits_per_batch'] = circuits_per_batch
        self['num_shots'] = num_shots
        # Populated when submitting to IBM Q with .submit()
        self['qjob'] = None
        self['job_ids'] = None
        # Populated when grabbing results from IBM Q with .retrieve_results()
        self['batch_result_object'] = None
        self['data'] = None
        self['DD_data'] = None 
        self.DD = parallel_DD
        if self.DD: 
            assert(backend is not None), "Can only do DD given a specific backend!"

        circuits = edesign.all_circuits_needing_data.copy()
        if randomized_order:
            if remove_duplicates:
                circuits = list(set(circuits))
            rng = _np.random.default_rng(seed)
            rng.shuffle(circuits)
            
        else:
            assert(not remove_duplicates), "Can only remove duplicates if randomizing order!"

        if self.DD: 
            circuits_per_batch = circuits_per_batch/2

        num_batches = int(_np.ceil(len(circuits) / circuits_per_batch))

        self['pygsti_circuits'] = [[] for i in range(num_batches)]
        self['pygsti_openqasm_circuits'] = [[] for i in range(num_batches)]
        self['qiskit_QuantumCircuits'] = [[] for i in range(num_batches)]
        self['qiskit_QuantumCircuits_as_openqasm'] = [[] for i in range(num_batches)]
        self['submit_time_calibration_data'] = []
        self['qobj'] = []

        batch_idx = 0
        for circ_idx, circ in enumerate(circuits):
            self['pygsti_circuits'][batch_idx].append(circ)
            if len(self['pygsti_circuits'][batch_idx]) == circuits_per_batch:
                batch_idx += 1

        #create Qiskit quantum circuit for each circuit defined in experiment list
        total_num = 0

        #start = _time.time()
        for batch_idx, circuit_batch in enumerate(self['pygsti_circuits']):
            print("Constructing job for circuit batch {} of {}".format(batch_idx + 1, num_batches))
            #openqasm_circuit_ids = []
            for circ_idx, circ in enumerate(circuit_batch):
                pygsti_openqasm_circ = circ.convert_to_openqasm(num_qubits=pspec.num_qubits,
                                                                standard_gates_version='x-sx-rz', ancilla_label=ancilla_label)
                qiskit_qc = _qiskit.QuantumCircuit.from_qasm_str(pygsti_openqasm_circ)
                self['pygsti_openqasm_circuits'][batch_idx].append(pygsti_openqasm_circ)
                self['qiskit_QuantumCircuits'][batch_idx].append(qiskit_qc)
                self['qiskit_QuantumCircuits_as_openqasm'][batch_idx].append(qiskit_qc.qasm())
                if self.DD: 
                    dd_circ = insert_dd(qiskit_qc, backend)
                    self['qiskit_QuantumCircuits'][batch_idx].append(dd_circ)
                    self['qiskit_QuantumCircuits_as_openqasm'][batch_idx].append(dd_circ.qasm())
                #print(batch_idx, circ_idx, len(submitted_openqasm_circuits), total_num)
                total_num += 1

            try:
                self['qobj'].append(_qiskit.compiler.assemble(self['qiskit_QuantumCircuits'][batch_idx], shots=num_shots))
            except:
                _warnings.warn("Couldn't create qobj!")
                self['qobj'] = None

    def submit(self, ibmq_backend, start=None, stop=None, ignore_job_limit=True,
               wait_time=1, wait_steps=10):
        """
        Submits the jobs to IBM Q, that implements the experiment specified by the ExperimentDesign
        used to create this object.

        Parameters
        ----------
        ibmq_backend: qiskit.providers.ibmq.ibmqbackend.IBMQBackend
            The IBM Q backend to submit the jobs to. Should be the backend corresponding to the
            processor that this experiment has been designed for.

        start: int, optional
            Batch index to start submission (inclusive). Defaults to None,
            which will start submission on the first unsubmitted job.
            Jobs can be resubmitted by manually specifying this,
            i.e. start=0 will start resubmitting jobs from the beginning.

        stop: int, optional
            Batch index to stop submission (exclusive). Defaults to None,
            which will submit as many jobs as possible given the backend's
            maximum job limit.

        ignore_job_limit: bool, optional
            If True, then stop is set to submit all remaining jobs. This is set
            as True to maintain backwards compatibility. Note that is more jobs
            are needed than the max limit, this will enter a wait loop until all
            jobs have been successfully submitted.

        wait_time: int
            Number of seconds for each waiting step.

        wait_steps: int
            Number of steps to take before retrying job submission.

        Returns
        -------
        None
        """
        
        #Get the backend version
        backend_version = ibmq_backend.version
        
        total_waits = 0
        self['qjob'] = [] if self['qjob'] is None else self['qjob']
        self['job_ids'] = [] if self['job_ids'] is None else self['job_ids']

        # Set start and stop to submit the next unsubmitted jobs if not specified
        if start is None:
            start = len(self['qjob'])

        if stop is not None:
            stop = min(stop, len(self['qobj']))
        elif ignore_job_limit:
            stop = len(self['qobj'])
        else:
            job_limit = ibmq_backend.job_limit()
            allowed_jobs = job_limit.maximum_jobs - job_limit.active_jobs
            if start + allowed_jobs < len(self['qobj']):
                print(f'Given job limit and active jobs, only {allowed_jobs} can be submitted')

            stop = min(start + allowed_jobs, len(self['qobj']))
        
        #if the backend version is 1 I believe this should correspond to the use of the legacy
        #qiskit-ibmq-provider API which supports passing in Qobj objects for specifying experiments
        #if the backend version is 2 I believe this should correspond to the new API in qiskit-ibm-provider.
        #This new API doesn't support passing in Qobjs into the run method for backends, so we need
        #to pass in the list of QuantumCircuit objects directly.
        if backend_version == 1:
            batch_iterator = enumerate(self['qobj'])
        elif backend_version >= 2:
            batch_iterator = enumerate(self['qiskit_QuantumCircuits'])

        start_time = _time.time() #Changed this 
        for batch_idx, batch in batch_iterator:
            if batch_idx < start or batch_idx >= stop:
                continue
                
            print("Submitting batch {}".format(batch_idx + 1))
            submit_status = False
            batch_waits = 0
            while not submit_status:
                try:
                    backend_properties = ibmq_backend.properties()
                    #If using a simulator backend then backend_properties is None
                    if not ibmq_backend.simulator:
                        self['submit_time_calibration_data'].append(backend_properties.to_dict())
                    #if using the new API we need to pass in the number of shots.
                    if backend_version == 1:
                        self['qjob'].append(ibmq_backend.run(batch))
                    else:
                        self['qjob'].append(ibmq_backend.run(batch, shots = self['num_shots']))
                        
                    status = self['qjob'][-1].status()
                    initializing = True
                    initializing_steps = 0
                    while initializing:
                        if status.name == 'INITIALIZING' or status.name == 'VALIDATING':
                            #print(status)
                            status = self['qjob'][-1].status()
                            print('  - {} (query {})'.format(status, initializing_steps))
                            _time.sleep(1)
                            initializing_steps += 1
                        else:
                            initializing = False
                    #print("   -Done intializing.  Job status is {}".format(status.name))
                    #print(status)
                    try:
                        job_id = self['qjob'][-1].job_id()
                        print('  - Job ID is {}'.format(job_id))
                        self['job_ids'].append(job_id)
                    except:
                        print('  - Failed to get job_id.')
                        self['job_ids'].append(None)
                    try:
                        print('  - Queue position is {}'.format(self['qjob'][-1].queue_info().position))
                    except:
                        print('  - Failed to get queue position for batch {}'.format(batch_idx + 1))
                    submit_status = True
                except Exception as ex:
                    template = "An exception of type {0} occurred. Arguments:\n{1!r}"
                    message = template.format(type(ex).__name__, ex.args)
                    print(message)
                    try:
                        print('Machine status is {}.'.format(ibmq_backend.status().status_msg))
                    except Exception as ex1:
                        print('Failed to get machine status!')
                        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
                        message = template.format(type(ex).__name__, ex1.args)
                        print(message)
                    total_waits += 1
                    batch_waits += 1
                    print("This batch has failed {0} times and there have been {1} total failures".format(
                        batch_waits, total_waits))
                    print('Waiting ', end='')
                    for step in range(wait_steps):
                        print('{} '.format(step), end='')
                        _time.sleep(wait_time)
                    print()
        end_time = _time.time() #Changed this 
        print(end_time - start_time, 'seconds to submit jobs') #Changed this 

    def monitor(self):
        """
        Queries IBM Q for the status of the jobs.
        """
        for counter, qjob in enumerate(self['qjob']):
            status = qjob.status()
            print("Batch {}: {}".format(counter + 1, status))
            if status.name == 'QUEUED':
                print('  - Queue position is {}'.format(qjob.queue_position(refresh=True))) #Changed this

        # Print unsubmitted for any entries in qobj but not qjob
        for counter in range(len(self['qjob']), len(self['qobj'])):
            print("Batch {}: NOT SUBMITTED".format(counter + 1))
            
        print(_datetime.datetime.now().strftime('Last query: %H:%M:%S')) #Changed this 

    def retrieve_results(self):
        """
        Gets the results of the completed jobs from IBM Q, and processes
        them into a pyGSTi DataProtocol object (stored as the key 'data'),
        which can then be used in pyGSTi data analysis routines (e.g., if this
        was a GST experiment, it can input into a GST protocol object that will
        analyze the data).
        """
        self['batch_result_object'] = []
        #get results from backend jobs and add to dict
        ds = _data.DataSet()
        if self.DD: 
            dd_ds = _data.DataSet()

        for exp_idx, qjob in enumerate(self['qjob']):
            print("Querying IBMQ for results objects for batch {}...".format(exp_idx + 1))
            batch_result = qjob.result()
            self['batch_result_object'].append(batch_result)
            #exp_dict['batch_data'] = []
            num_qubits_in_pspec = self['pspec'].num_qubits
            for i, circ in enumerate(self['pygsti_circuits'][exp_idx]): 
                if self.DD: 
                    ordered_target_indices = [self['pspec'].qubit_labels.index(q) for q in circ.line_labels]
                    #assumes qubit labeling of the form 'Q0' not '0' 
                    labeled_counts = to_labeled_counts(batch_result.get_counts(2*i), ordered_target_indices, num_qubits_in_pspec)
                    dd_labeled_counts = to_labeled_counts(batch_result.get_counts(2*i+1), ordered_target_indices, num_qubits_in_pspec)
                    outcome_labels = labeled_counts[0]
                    counts_data = labeled_counts[1]
                    dd_outcome_labels = dd_labeled_counts[0]
                    dd_counts_data = dd_labeled_counts[1]
                    ds.add_count_list(circ, outcome_labels, counts_data)
                    dd_ds.add_count_list(circ, dd_outcome_labels, dd_counts_data)
                else: 
                    ordered_target_indices = [self['pspec'].qubit_labels.index(q) for q in circ.line_labels]
                    #assumes qubit labeling of the form 'Q0' not '0' 
                    labeled_counts = to_labeled_counts(batch_result.get_counts(i), ordered_target_indices, num_qubits_in_pspec)
                    outcome_labels = labeled_counts[0]
                    counts_data = labeled_counts[1]
                    ds.add_count_list(circ, outcome_labels, counts_data)              
        self['data'] = _ProtocolData(self['edesign'], ds)
        if self.DD: 
            self['DD_data'] = _ProtocolData(self['edesign'], dd_ds)
        print('Finished retrieving results!') #Changed this 

    def write(self, dirname=None):
        """
        Writes to disk, storing both the pyGSTi DataProtocol object in pyGSTi's standard
        format and saving all of the IBM Q submission information stored in this object,
        written into the subdirectory 'ibmqexperiment'.

        Parameters
        ----------
        dirname : str
            The *root* directory to write into.  This directory will have
            an 'edesign' subdirectory, which will be created if needed and
            overwritten if present.  If None, then the path this object
            was loaded from is used (if this object wasn't loaded from disk,
            an error is raised).
        """
        if dirname is None:
            dirname = self['edesign']._loaded_from
            if dirname is None: raise ValueError("`dirname` must be given because there's no default directory")

        self['data'].write(dirname)
        if self.DD:
            self['DD_data'].write(dirname)

        dict_to_json = {atr: self[atr] for atr in _attribute_to_json}

        _os.mkdir(dirname + '/ibmqexperiment')
        with open(dirname + '/ibmqexperiment/meta.json', 'w') as f:
            _json.dump(dict_to_json, f, indent=4)

        for atr in _attribute_to_pickle:
            with open(dirname + '/ibmqexperiment/{}.pkl'.format(atr), 'wb') as f:
                _pickle.dump(self[atr], f)

    @classmethod
    def from_dir(cls, dirname, provider=None):
        """
        Initialize a new IBMQExperiment object from `dirname`.

        Parameters
        ----------
        dirname : str
            The directory name.
        
        provider: IBMProvider
            Provider used to retrieve qjob objects from job_ids

        Returns
        -------
        IBMQExperiment
        """
        ret = cls.__new__(cls)
        with open(dirname + '/ibmqexperiment/meta.json', 'r') as f:
            from_json = _json.load(f)
        ret.update(from_json)

        for atr in _attribute_to_pickle:
            with open(dirname + '/ibmqexperiment/{}.pkl'.format(atr), 'rb') as f:
                try:
                    ret[atr] = _pickle.load(f)
                except:
                    _warnings.warn("Couldn't unpickle {}, so skipping this attribute.".format(atr))
                    ret[atr] = None

        if provider is None:
            _warnings.warn("No provider specified, cannot retrieve IBM jobs")
        else:
            ret['qjob'] = []
            for i, jid in enumerate(ret['job_ids']):
                print(f"Loading job {i+1}/{len(ret['job_ids'])}...")
                ret['qjob'].append(provider.backend.retrieve_job(jid))

        try:
            ret['data'] = _ProtocolData.from_dir(dirname)
        except:
            pass

        return ret


class IBMQRuntimeExperiment(dict):

    def __init__(self, edesign, pspec, ancilla_label=None,remove_duplicates=True, randomized_order=True, seed=None, circuits_per_batch=75,
                 num_shots=1024, backend=None):
        """
        A object that converts pyGSTi ExperimentDesigns into jobs to be submitted to IBM Q, submits these
        jobs to IBM Q and receives the results.

        Parameters
        ----------
        edesign: ExperimentDesign
            The ExperimentDesign to be run on IBM Q. This can be a combined experiment design (e.g., a GST
            design combined with an RB design).

        pspec: QubitProcessorSpec
            A QubitProcessorSpec that represents the IBM Q device being used. This can be created using the
            extras.devices.create_processor_spec(). The ProcessorSpecs qubit ordering *must* correspond
            to that of the IBM device (which will be the case if you create it using that function).
            I.e., pspecs qubits should be labelled Q0 through Qn-1 and the labelling of the qubits
            should agree with IBM's labelling.

        remove_duplicates: bool, optional
            If true, each distinct circuit in `edesign` is run only once. If false, if a circuit is
            repeated multiple times in `edesign` it is run multiple times.

        randomized_order: bool, optional
            Whether or not to randomize the order of the circuits in `edesign` before turning them
            into jobs to be submitted to IBM Q.

        seed: int or None, optional
            Seed to be used in randomization. 

        circuits_per_batch: int, optional
            The circuits in edesign are divded into batches, each containing at most this many
            circuits. The default value of 75 is (or was) the maximal value allowed on the public
            IBM Q devices.

        num_shots: int, optional
            The number of samples from / repeats of each circuit.

        Returns
        -------
        IBMQExperiment
            An object containing jobs to be submitted to IBM Q, which can then be submitted
            using the methods .submit() and whose results can be grabbed from IBM Q using
            the method .retrieve_results(). This object has dictionary-like access for all of
            the objects it contains (e.g., ['qobj'] is a list of the objects to be submitted to
            IBM Q).

        """

        self['edesign'] = edesign
        self['pspec'] = pspec
        self['remove_duplicates'] = remove_duplicates
        self['randomized_order'] = randomized_order
        self['seed'] = seed #Changed this 
        self['circuits_per_batch'] = circuits_per_batch
        self['num_shots'] = num_shots
        # Populated when submitting to IBM Q with .submit()
        self['qjob'] = None
        self['job_ids'] = None
        # Populated when grabbing results from IBM Q with .retrieve_results()
        self['batch_result_object'] = None
        self['data'] = None

        circuits = edesign.all_circuits_needing_data.copy()
        if randomized_order:
            if remove_duplicates:
                circuits = list(set(circuits))
            rng = _np.random.default_rng(seed)
            rng.shuffle(circuits)
            
        else:
            assert(not remove_duplicates), "Can only remove duplicates if randomizing order!"

        num_batches = int(_np.ceil(len(circuits) / circuits_per_batch))

        self['pygsti_circuits'] = [[] for i in range(num_batches)]
        self['pygsti_openqasm_circuits'] = [[] for i in range(num_batches)]
        self['qiskit_QuantumCircuits'] = [[] for i in range(num_batches)]
        self['qiskit_ISA_QuantumCircuits'] = []
        self['submit_time_calibration_data'] = []
        self['qobj'] = []

        batch_idx = 0
        for circ_idx, circ in enumerate(circuits):
            self['pygsti_circuits'][batch_idx].append(circ)
            if len(self['pygsti_circuits'][batch_idx]) == circuits_per_batch:
                batch_idx += 1

        #create Qiskit quantum circuit for each circuit defined in experiment list
        total_num = 0
        #start = _time.time()
        for batch_idx, circuit_batch in enumerate(self['pygsti_circuits']):
            print("Constructing job for circuit batch {} of {}".format(batch_idx + 1, num_batches))
            #openqasm_circuit_ids = []
            for circ_idx, circ in enumerate(circuit_batch):
                pygsti_openqasm_circ = circ.convert_to_openqasm(num_qubits=pspec.num_qubits,
                                                                standard_gates_version='x-sx-rz', ancilla_label=ancilla_label)
                qiskit_qc = _qiskit.QuantumCircuit.from_qasm_str(pygsti_openqasm_circ)
                self['pygsti_openqasm_circuits'][batch_idx].append(pygsti_openqasm_circ)
                self['qiskit_QuantumCircuits'][batch_idx].append(qiskit_qc)
                #print(batch_idx, circ_idx, len(submitted_openqasm_circuits), total_num)
                total_num += 1

            try:
                self['qobj'].append(_qiskit.compiler.assemble(self['qiskit_QuantumCircuits'][batch_idx], shots=num_shots))
            except:
                _warnings.warn("Couldn't create qobj!")
                self['qobj'] = None

    def submit(self, ibmq_backend, start=None, stop=None, ignore_job_limit=True,
               wait_time=1, wait_steps=10, opt_level = 0):
        """
        Submits the jobs to IBM Q, that implements the experiment specified by the ExperimentDesign
        used to create this object.

        Parameters
        ----------
        ibmq_mode: qiskit.providers.ibmq.ibmqbackend.IBMQBackend
            The IBM Q backend to submit the jobs to. Should be the backend corresponding to the
            processor that this experiment has been designed for.

        start: int, optional
            Batch index to start submission (inclusive). Defaults to None,
            which will start submission on the first unsubmitted job.
            Jobs can be resubmitted by manually specifying this,
            i.e. start=0 will start resubmitting jobs from the beginning.

        stop: int, optional
            Batch index to stop submission (exclusive). Defaults to None,
            which will submit as many jobs as possible given the backend's
            maximum job limit.

        ignore_job_limit: bool, optional
            If True, then stop is set to submit all remaining jobs. This is set
            as True to maintain backwards compatibility. Note that is more jobs
            are needed than the max limit, this will enter a wait loop until all
            jobs have been successfully submitted.

        wait_time: int
            Number of seconds for each waiting step.

        wait_steps: int
            Number of steps to take before retrying job submission.

        Returns
        -------
        None
        """
        
        total_waits = 0
        self['qjob'] = [] if self['qjob'] is None else self['qjob']
        self['job_ids'] = [] if self['job_ids'] is None else self['job_ids']

        # Set start and stop to submit the next unsubmitted jobs if not specified
        pm = generate_preset_pass_manager(backend=ibmq_backend, optimization_level=opt_level)
        batch_iterator = enumerate(self['qiskit_QuantumCircuits'])
        ibmq_session = Session(backend = ibmq_backend)
        sampler = Sampler(session=ibmq_session)

        start_time = _time.time() #Changed this 
        for batch_idx, batch in batch_iterator:
            print("Submitting batch {}".format(batch_idx + 1))
            submit_status = False
            batch_waits = 0
            while not submit_status:
                try:
                    backend_properties = ibmq_backend.properties()
                    #If using a simulator backend then backend_properties is None
                    if not ibmq_backend.simulator:
                        self['submit_time_calibration_data'].append(backend_properties.to_dict())
                    isa_qcs = pm.run(batch)
                    self['qjob'].append(sampler.run(isa_qcs, shots = self['num_shots']))
                    self['qiskit_ISA_QuantumCircuits'] += [isa_qcs]

                    status = self['qjob'][-1].status()
                    initializing = True
                    initializing_steps = 0
                    while initializing:
                        if status == 'QUEUED':
                            initializing = False
                        elif status.name == 'INITIALIZING' or status.name == 'VALIDATING':
                            #print(status)
                            status = self['qjob'][-1].status()
                            print('  - {} (query {})'.format(status, initializing_steps))
                            _time.sleep(1)
                            initializing_steps += 1
                    #print("   -Done intializing.  Job status is {}".format(status.name))
                    #print(status)
                    try:
                        job_id = self['qjob'][-1].job_id()
                        print('  - Job ID is {}'.format(job_id))
                        self['job_ids'].append(job_id)
                    except:
                        print('  - Failed to get job_id.')
                        self['job_ids'].append(None)
                    try:
                        print('  - Queue position is {}'.format(self['qjob'][-1].queue_info().position))
                    except:
                        print('  - Failed to get queue position for batch {}'.format(batch_idx + 1))
                    submit_status = True
                except Exception as ex:
                    template = "An exception of type {0} occurred. Arguments:\n{1!r}"
                    message = template.format(type(ex).__name__, ex.args)
                    print(message)
                    try:
                        print('Machine status is {}.'.format(ibmq_backend.status().status_msg))
                    except Exception as ex1:
                        print('Failed to get machine status!')
                        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
                        message = template.format(type(ex).__name__, ex1.args)
                        print(message)
                    total_waits += 1
                    batch_waits += 1
                    print("This batch has failed {0} times and there have been {1} total failures".format(
                        batch_waits, total_waits))
                    print('Waiting ', end='')
                    for step in range(wait_steps):
                        print('{} '.format(step), end='')
                        _time.sleep(wait_time)
                    print()
        end_time = _time.time() #Changed this 
        print(end_time - start_time, 'seconds to submit jobs') #Changed this 

    def monitor(self):
        """
        Queries IBM Q for the status of the jobs.
        """
        for counter, qjob in enumerate(self['qjob']):
            status = qjob.status()
            print("Batch {}: {}".format(counter + 1, status))
            if status == 'QUEUED':
                print('  - Queue position is {}'.format(qjob.queue_position(refresh=True))) #Changed this

        # Print unsubmitted for any entries in qobj but not qjob
        for counter in range(len(self['qjob']), len(self['qobj'])):
            print("Batch {}: NOT SUBMITTED".format(counter + 1))
            
        print(_datetime.datetime.now().strftime('Last query: %H:%M:%S')) #Changed this 

    def retrieve_results(self):
        """
        Gets the results of the completed jobs from IBM Q, and processes
        them into a pyGSTi DataProtocol object (stored as the key 'data'),
        which can then be used in pyGSTi data analysis routines (e.g., if this
        was a GST experiment, it can input into a GST protocol object that will
        analyze the data).
        """
        self['batch_result_object'] = []
        #get results from backend jobs and add to dict
        ds = _data.DataSet()


        for exp_idx, qjob in enumerate(self['qjob']):
            print("Querying IBMQ for results objects for batch {}...".format(exp_idx + 1))
            batch_result = qjob.result()
            self['batch_result_object'].append(batch_result)
            #exp_dict['batch_data'] = []
            num_qubits_in_pspec = self['pspec'].num_qubits
            for i, circ in enumerate(self['pygsti_circuits'][exp_idx]): 
                ordered_target_indices = [self['pspec'].qubit_labels.index(q) for q in circ.line_labels]
                #assumes qubit labeling of the form 'Q0' not '0' 
                labeled_counts = to_labeled_counts(batch_result[i].data.cr.get_counts(), ordered_target_indices, num_qubits_in_pspec)
                outcome_labels = labeled_counts[0]
                counts_data = labeled_counts[1]
                ds.add_count_list(circ, outcome_labels, counts_data)              
        self['data'] = _ProtocolData(self['edesign'], ds)
        print('Finished retrieving results!') #Changed this 

    def write(self, dirname=None):
        """
        Writes to disk, storing both the pyGSTi DataProtocol object in pyGSTi's standard
        format and saving all of the IBM Q submission information stored in this object,
        written into the subdirectory 'ibmqexperiment'.

        Parameters
        ----------
        dirname : str
            The *root* directory to write into.  This directory will have
            an 'edesign' subdirectory, which will be created if needed and
            overwritten if present.  If None, then the path this object
            was loaded from is used (if this object wasn't loaded from disk,
            an error is raised).
        """
        if dirname is None:
            dirname = self['edesign']._loaded_from
            if dirname is None: raise ValueError("`dirname` must be given because there's no default directory")

        self['data'].write(dirname)

        dict_to_json = {atr: self[atr] for atr in _attribute_to_json}

        _os.mkdir(dirname + '/ibmqexperiment')
        with open(dirname + '/ibmqexperiment/meta.json', 'w') as f:
            _json.dump(dict_to_json, f, indent=4)

        for atr in _attribute_to_pickle_runtime:
            with open(dirname + '/ibmqexperiment/{}.pkl'.format(atr), 'wb') as f:
                _pickle.dump(self[atr], f)

    @classmethod
    def from_dir(cls, dirname, provider=None):
        """
        Initialize a new IBMQExperiment object from `dirname`.

        Parameters
        ----------
        dirname : str
            The directory name.
        
        provider: IBMProvider
            Provider used to retrieve qjob objects from job_ids

        Returns
        -------
        IBMQExperiment
        """
        ret = cls.__new__(cls)
        with open(dirname + '/ibmqexperiment/meta.json', 'r') as f:
            from_json = _json.load(f)
        ret.update(from_json)

        for atr in _attribute_to_pickle:
            with open(dirname + '/ibmqexperiment/{}.pkl'.format(atr), 'rb') as f:
                try:
                    ret[atr] = _pickle.load(f)
                except:
                    _warnings.warn("Couldn't unpickle {}, so skipping this attribute.".format(atr))
                    ret[atr] = None

        if provider is None:
            _warnings.warn("No provider specified, cannot retrieve IBM jobs")
        else:
            ret['qjob'] = []
            for i, jid in enumerate(ret['job_ids']):
                print(f"Loading job {i+1}/{len(ret['job_ids'])}...")
                ret['qjob'].append(provider.backend.retrieve_job(jid))

        try:
            ret['data'] = _ProtocolData.from_dir(dirname)
        except:
            pass

        return ret
