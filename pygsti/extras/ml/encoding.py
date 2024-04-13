import numpy as _np

from pygsti.processors.processorspec import QubitProcessorSpec as QPS
from pygsti.extras.ml.newtools import create_error_propagation_matrix

###### Functions that encode a circuit into a tensor ###

# TO DO: Make more general

qubit_to_index = {0:0, 1:1, 2:2, 3:3}
geometry_cnot_channels = {'ring': 4, 'linear': 4, 'grid': 8} # you get 2 channels for each cnot gate

def compute_channels(pspec: QPS, geometry: str) -> int:
    return len(pspec.gate_names) - 1 + geometry_cnot_channels[geometry]
           
def clockwise_cnot(g, num_qubits):
    return (g.qubits[0] - g.qubits[1]) % num_qubits == num_qubits - 1

def algiers_t_bar_gate_to_index(g, q, pspec)-> int:
    '''
    Works for Ourense, Belem, etc.
    '''
    assert(q in g.qubits)
    single_qubit_gates = list(pspec.gate_names)
    single_qubit_gates.remove('Gcnot')
    if g.name == 'Gcnot':
        if g.qubits in [(0,1), (1,4)]:
            if q == g.qubits[0]: return 0
            else: return 1
        elif g.qubits in [(1,0), (4,1)]:
            if q == g.qubits[0]: return 2
            else: return 3
        elif g.qubits in [(1,2), (3,2)]:
            if q == g.qubits[0]: return 4
            else: return 5
        elif g.qubits in [(2,1), (2,3)]:
            if q == g.qubits[0]: return 6
            else: return 7
        else:
            raise ValueError('Invalid gate name for this encoding!')
    elif g.name in pspec.gate_names:
        # We have a single-qubit Clifford gate
        return 8+single_qubit_gates.index(g.name) # we put the single-qubit gates after the CNOT channels.
    else:
        raise ValueError('Invalid gate name for this encoding!')

def t_bar_gate_to_index(g, q, pspec)-> int:
    '''
    Works for Ourense, Belem, etc.
    '''
    assert(q in g.qubits)
    single_qubit_gates = list(pspec.gate_names)
    single_qubit_gates.remove('Gcnot')
    if g.name == 'Gcnot':
        if g.qubits in [('Q0','Q1'), ('Q1', 'Q2')]:
            if q == int(g.qubits[0][1:]): return 0
            else: return 1
        elif g.qubits in [('Q1','Q0'), ('Q2','Q1')]:
            if q == int(g.qubits[0][1:]): return 2
            else: return 3
        elif g.qubits in [('Q1','Q3'), ('Q3','Q4')]:
            if q == int(g.qubits[0][1:]): return 4
            else: return 5
        elif g.qubits in [('Q3','Q1'), ('Q4','Q3')]:
            if q == int(g.qubits[0][1:]): return 6
            else: return 7
        else:
            raise ValueError('Invalid gate name for this encoding!')
    elif g.name in pspec.gate_names:
        # We have a single-qubit Clifford gate
        return 8+single_qubit_gates.index(g.name) # we put the single-qubit gates after the CNOT channels.
    else:
        raise ValueError('Invalid gate name for this encoding!')

def ring_gate_to_index(g, q, num_qubits):
    assert(q in g.qubits)
    if g.name == 'Gxpi2':
        return 0
    elif g.name == 'Gypi2':
        return 1
    elif g.name == 'Gcnot':
        qs = g.qubits
        if q == g.qubits[0] and clockwise_cnot(g, num_qubits):
            return 2
        if q == g.qubits[1] and clockwise_cnot(g, num_qubits):
            return 3
        if q == g.qubits[0] and not clockwise_cnot(g, num_qubits):
            return 4
        if q == g.qubits[1] and not clockwise_cnot(g, num_qubits):
            return 5
    else:
        raise ValueError('Invalid gate name for this encoding!')
    
def layer_to_matrix(layer, num_qubits = None, num_channels = None, 
                    indexmapper = None, indexmapper_kwargs = {}, 
                    valuemapper = None, valuemapper_kwargs = {}) -> _np.array:
    '''
    Function that encodes a layer into a matrix. 
        
    valuemapper: a function that maps a gate to a specific value
    
    indexmapper: a function that maps a gate to an index.
    '''
    if valuemapper is None: valuemapper = lambda x: 1
    if num_qubits is None: num_qubits = layer.num_lines
    assert(num_channels is not None), 'I need to know the number of channels per qubit!'
    assert(indexmapper is not None), 'I need a way to map a gate to an index!!!'

    mat = _np.zeros((num_qubits, num_channels), float)
    for g in layer:
        for q in g.qubits:
            if type(q) == str: q_index = int(q[1:])
            else: q_index = q
            mat[q_index, indexmapper(g, q, **indexmapper_kwargs)] = valuemapper(g, **valuemapper_kwargs)
    return mat

def circuit_to_tensor(circ, depth = None, num_qubits = None, num_channels = None, add_measurements = False, 
                      indexmapper = None, indexmapper_kwargs = None, 
                      valuemapper = None, valuemapper_kwargs = {}) -> _np.array:
    '''
    Function that transforms a circuit into a numpy array/tensor.

    valuemapper: a function that maps gates to numeric values.

    indexmapper: a function that maps gates to indices.

    The add measurements functionality assumes that gates are always encoded as a postive value.
    '''
    
    if depth is None: depth = circ.depth
    if num_qubits is None: num_qubits = circ.num_lines
    assert(num_channels is not None), 'I need to know how many channels there are per qubit.'
    ctensor = _np.zeros((num_qubits, depth, num_channels), float)
    for i in range(circ.depth):
        ctensor[:, i, :] = layer_to_matrix(circ.layer(i), num_qubits, num_channels, 
                                           indexmapper, indexmapper_kwargs, 
                                           valuemapper, valuemapper_kwargs)
    if add_measurements:
        row_sums = _np.sum(ctensor, axis = (1, 2)) # Figure out which qubits are dark (i.e., unused)
        used_qubits = _np.where(row_sums != 0)  
        ctensor[used_qubits[0], -1, -1] = 1       
    return ctensor

def active_qubits(ctensor):
    row_sums = _np.sum(ctensor, axis = (1,2))
    used_qubits = _np.where(row_sums != 0)
    measurement = _np.zeros(ctensor.shape[0])
    measurement[used_qubits[0]] = 1 
    return measurement

# def screen_z_errors(P, measurement):
#     """
#     A function that takes in a circuit's permutation matrix and its measurement tensor (i.e., the matrices that tell you where every 
#     error vector gets mapped to at the end of the circuit) and creates a mask that masks out
#     all error's that are Z-type on the active qubits in a circuit. 
#     """
#     active_qubits = _tf.where(measurement == 1)[:, 0]
#     flattened_P = _tf.reshape(P, [-1])
#     unique_P, _ = _tf.unique(flattened_P) # Get the unique values in P as well as their indices. 
#     condition_mask = _tf.map_fn(lambda x: good_error(x, active_qubits), unique_P, fn_output_signature=_tf.bool)
#     good_errors = _tf.boolean_mask(unique_P, condition_mask)
#     expand_flat_P = _tf.expand_dims(flattened_P, axis = -1)
#     masked_P = _tf.reduce_any(_tf.equal(expand_flat_P, good_errors), axis = -1)
#     masked_P = _tf.reshape(masked_P, P.shape)
#     masked_P = _tf.cast(masked_P, _tf.float32)
    
#     return masked_P

def z_mask(P, measurement):
    """
    A function that takes in a circuit's permutation matrix and its measurement tensor (i.e., the matrices that tell you where every 
    error vector gets mapped to at the end of the circuit) and creates a mask that masks out
    all error's that are Z-type on the active qubits in a circuit. 
    """
    return _np.zeros(P.shape)

        
def create_input_data(circs:list, fidelities:list, tracked_error_gens: list, 
                      pspec, geometry: str, num_qubits = None, num_channels = None, 
                      measurement_encoding = None,
                      indexmapper = None, indexmapper_kwargs = {}, 
                      valuemapper = None, valuemapper_kwargs = {},
                      max_depth = None, return_separate=False):
    '''
    Maps a list of circuits and fidelities to numpy arrays of encoded circuits and fidelities. 

    Args:
       - tracked_error_gens: a list of the tracked error generators.
       - pspec: the processor on which the circuits are defined. Used to determine the number of qubits and channels (optional)
       - geometry: the geometry in which you plan to embed the circuits (i.e., ring, grid, linear). Optional.
       - num_qubits: the number of qubits (optional, if pspec and geometry are specified)
       - num_channels: the number of channels used to embed a (qubit, gate) pair (optional, if pspec and geometry are specified.)
       - indexmapper: function specifying how to map a gate to a channel.
       - valuemapper: function specifying how to encode each gate in pspec (optional, defaults to assigning each gate a value of 1)
       - measurement_encoding: int or NoneType specifying how to encode measurements. 
            - If NoneType, then no measurements are returned.
            - If 1, then measurements are encoded as extra channels in the circuit tensor.
            - If 2, then the measurements are returned separately in a tensor of shape (num_qubits,)
    '''
    num_circs = len(circs)
    num_error_gens = len(tracked_error_gens)

    if max_depth is None: max_depth = _np.max([c.depth for c in circs])
    print(max_depth)
    
    if num_channels is None: num_channels = compute_channels(pspec, geometry)
    encode_measurements = False
    if measurement_encoding == 1:
        encode_measurements = True
        num_channels += 1
        max_depth += 1 # adding an additional layer to each circuit for the measurements.
    elif measurement_encoding == 2:
        measurements = _np.zeros((num_circs, num_qubits))
        x_zmask = _np.zeros((num_circs, max_depth, num_error_gens), int)
    
    if num_qubits is None: num_qubits = len(pspec.qubit_labels)
    if valuemapper is None: valuemapper = lambda x: 1
    assert(indexmapper is not None), 'I need a way to map gates to an index!!!!'

    x_circs = _np.zeros((num_circs, num_qubits, max_depth, num_channels), float)
    x_signs = _np.zeros((num_circs, max_depth, num_error_gens), int)
    x_indices = _np.zeros((num_circs, max_depth, num_error_gens), int)
    if type(fidelities) is list: y = _np.array(fidelities)
                    
    for i, c in enumerate(circs):
        if i % 200 == 0:
            print(i, end=',')
        x_circs[i, :, :, :] = circuit_to_tensor(c, max_depth, num_qubits, num_channels, encode_measurements,
                                                         indexmapper, indexmapper_kwargs,
                                                         valuemapper, valuemapper_kwargs 
                                                         )              
        c_indices, c_signs = create_error_propagation_matrix(c, tracked_error_gens)
        x_indices[i, 0:c.depth, :] = c_indices # deprecated: np.rint(c_indices)
        x_signs[i, 0:c.depth, :] = c_signs # deprecated: np.rint(c_signs)
        if measurement_encoding == 1:
            # This is where update the signs and indices to account for the measurements
            # NOT IMPLEMENTED!!!!!
            x_signs[i, :, -1] = 1 
            x_indices[i, :, -1] = 0 # ??? Need to figure this out ??? Need to take the tracked error gens and map them to their unique id
        elif measurement_encoding == 2:
            measurements[i, :] = active_qubits(x_circs[i, :, :, :])
            x_zmask[i, 0:c.depth, :] = z_mask(c_indices, measurements[i, :])
           
    if return_separate:
        return x_circs, x_signs, x_indices, y

    else:
        len_gate_encoding = num_qubits * num_channels
        xc_reshaped = _np.zeros((x_circs.shape[0], x_circs.shape[2], x_circs.shape[1] * x_circs.shape[3]), float)
        for qi in range(num_qubits): 
            for ci in range(num_channels): 
                xc_reshaped[:, :, qi * num_channels + ci] = x_circs[:, qi, :, ci].copy()
            
        x = _np.zeros((x_indices.shape[0], x_indices.shape[1], 2 * num_error_gens + len_gate_encoding), float)
        x[:, :, 0:len_gate_encoding] = xc_reshaped[:, :, :]
        x[:, :, len_gate_encoding:num_error_gens + len_gate_encoding] = x_indices[:, :, :]
        x[:, :, num_error_gens + len_gate_encoding:2 * num_error_gens + len_gate_encoding] = x_signs[:, :, :]
        if measurement_encoding == 2:
            # xt = _np.concatenate((xt, x_zmask), axis = 0)
            return x, y, measurements
        return x, y
            
def old_create_input_data(circs:list, fidelities:list, tracked_error_gens: list, 
                      pspec, geometry: str, num_qubits = None, num_channels = None, 
                      measurement_encoding = None,
                      indexmapper = None, indexmapper_kwargs = {}, 
                      valuemapper = None, valuemapper_kwargs = {},
                      max_depth = None, return_separate=False):
    '''
    Maps a list of circuits and fidelities to numpy arrays of encoded circuits and fidelities. 

    Args:
       - tracked_error_gens: a list of the tracked error generators.
       - pspec: the processor on which the circuits are defined. Used to determine the number of qubits and channels (optional)
       - geometry: the geometry in which you plan to embed the circuits (i.e., ring, grid, linear). Optional.
       - num_qubits: the number of qubits (optional, if pspec and geometry are specified)
       - num_channels: the number of channels used to embed a (qubit, gate) pair (optional, if pspec and geometry are specified.)
       - indexmapper: function specifying how to map a gate to a channel.
       - valuemapper: function specifying how to encode each gate in pspec (optional, defaults to assigning each gate a value of 1)
       - measurement_encoding: int or NoneType specifying how to encode measurements. 
            - If NoneType, then no measurements are returned.
            - If 1, then measurements are encoded as extra channels in the circuit tensor.
            - If 2, then the measurements are returned separately in a tensor of shape (num_qubits,)
    '''
    num_circs = len(circs)
    num_error_gens = len(tracked_error_gens)

    if max_depth is None: max_depth = _np.max([c.depth for c in circs])
    print(max_depth)
    
    if num_channels is None: num_channels = compute_channels(pspec, geometry)
    encode_measurements = False
    if measurement_encoding == 1:
        encode_measurements = True
        num_channels += 1
        max_depth += 1 # adding an additional layer to each circuit for the measurements.
    elif measurement_encoding == 2:
        measurements = _np.zeros((num_circs, num_qubits))
    
    if num_qubits is None: num_qubits = len(pspec.qubit_labels)
    if valuemapper is None: valuemapper = lambda x: 1
    assert(indexmapper is not None), 'I need a way to map gates to an index!!!!'

    x_circs = _np.zeros((num_circs, num_qubits, max_depth, num_channels), float)
    x_signs = _np.zeros((num_circs, num_error_gens, max_depth), int)
    x_indices = _np.zeros((num_circs, num_error_gens, max_depth), int)
    if type(fidelities) is list: y = _np.array(fidelities)
                    
    for i, c in enumerate(circs):
        if i % 200 == 0:
            print(i, end=',')
        x_circs[i, :, :, :] = circuit_to_tensor(c, max_depth, num_qubits, num_channels, encode_measurements,
                                                         indexmapper, indexmapper_kwargs,
                                                         valuemapper, valuemapper_kwargs 
                                                         )              
        c_indices, c_signs = create_error_propagation_matrix(c, tracked_error_gens)
        # c_indices = remap_indices(c_indices)
        x_indices[i, :, 0:c.depth] = c_indices.T # deprecated: np.rint(c_indices)
        x_signs[i, :, 0:c.depth] = c_signs.T # deprecated: np.rint(c_signs)
        if measurement_encoding == 1:
            # This is where update the signs and indices to account for the measurements
            # NOT IMPLEMENTED!!!!!
            x_signs[i, :, -1] = 1 
            x_indices[i, :, -1] = 0 # ??? Need to figure this out ??? Need to take the tracked error gens and map them to their unique id
        elif measurement_encoding == 2:
            measurements[i, :] = active_qubits(x_circs[i, :, :, :])
           
    if return_separate:
        return x_circs, x_signs, x_indices, y

    else:
        len_gate_encoding = num_qubits * num_channels
        xc_reshaped = _np.zeros((x_circs.shape[0], x_circs.shape[1] * x_circs.shape[3], x_circs.shape[2]), float) 
        for qi in range(num_qubits): 
            for ci in range(num_channels): 
                xc_reshaped[:, qi * num_channels + ci, :] = x_circs[:, qi, :, ci].copy()

        xi2 = _np.transpose(x_indices, (0, 2, 1))
        xc2 = _np.transpose(xc_reshaped, (0, 2, 1))
        xs2 = _np.transpose(x_signs, (0, 2, 1))

        xt = _np.zeros((xi2.shape[0], xi2.shape[1], 2 * num_error_gens + len_gate_encoding), float)
        xt[:, :, 0:len_gate_encoding] = xc2[:, :, :]
        xt[:, :, len_gate_encoding:num_error_gens + len_gate_encoding] = xi2[:, :, :]
        xt[:, :, num_error_gens + len_gate_encoding:2 * num_error_gens + len_gate_encoding] = xs2[:, :, :]

        if measurement_encoding == 2:
            return xt, y, measurements
        return xt, y
        