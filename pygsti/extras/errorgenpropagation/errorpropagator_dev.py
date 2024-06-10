import stim
from pygsti.extras.errorgenpropagation.localstimerrorgen import LocalStimErrorgenLabel as _LSE
from numpy import abs,zeros, complex128
from numpy.linalg import multi_dot
from scipy.linalg import expm
from pygsti.tools.internalgates import standard_gatenames_stim_conversions
from pygsti.extras.errorgenpropagation.utilserrorgenpropagation import commute_errors

class ErrorGeneratorPropagator:

    def __init__(self, model, multi_gate_dict=None, bch_order=1,
                 bch_layerwise=False, nonmarkovian=False, multi_gate=False, 
                 error_layer_def=False):
        self.model = model
        self.bch_order = bch_order
        self.bch_layerwise = bch_layerwise    

    def propagate_errorgen_bch(circuit, bch_order, bch_layerwise):
        pass

    def propagate_errorgen_nonmarkovian(circuit, multi_gate_dict):
        pass

    


def ErrorPropagator(circ,errorModel,multi_gate_dict=None,bch_order=1,bch_layerwise=False,
                    nonmarkovian=False,multi_gate=False,error_layer_def=False):
    if multi_gate and multi_gate_dict is None:
        multi_gate_dict=dict()
    stim_dict=standard_gatenames_stim_conversions()
    if multi_gate:
        for key in multi_gate_dict:
            stim_dict[key]=stim_dict[multi_gate_dict[key]]
    stim_layers=circ.convert_to_stim_tableau_layers(gate_name_conversions=stim_dict)
    stim_layers.pop(0)  #Immediatly toss the first layer because it is not important,

    propagation_layers=[]
    if not bch_layerwise or nonmarkovian:
        while len(stim_layers) != 0:
            top_layer=stim_layers.pop(0)
            for layer in stim_layers:
                top_layer = layer*top_layer
            propagation_layers.append(top_layer)
    else:
        propagation_layers = stim_layers

    if not error_layer_def:
        errorLayers=buildErrorlayers(circ,errorModel,len(circ.line_labels))
    else:
        errorLayers=[[errorModel]]*circ.depth #this doesn't work

    num_error_layers=len(errorLayers)
    
    fully_propagated_layers=[]
    for _ in range(0,num_error_layers-1):
        err_layer=errorLayers.pop(0)
        layer=propagation_layers.pop(0)
        new_error_layer=[]
        for err_order in err_layer:
            new_error_dict=dict()
            for key in err_order:
                propagated_error_gen=key.propagate_error_gen_tableau(layer,err_order[key])
                new_error_dict[propagated_error_gen[0]]=propagated_error_gen[1]
            new_error_layer.append(new_error_dict)
        if bch_layerwise and not nonmarkovian:
            following_layer = errorLayers.pop(0)
            new_errors=BCH_Handler(err_layer,following_layer,bch_order)
            errorLayers.insert(new_errors,0)
        else:
            fully_propagated_layers.append(new_error_layer)

    fully_propagated_layers.append(errorLayers.pop(0))
    if bch_layerwise and not nonmarkovian:
        final_error=dict()
        for order in errorLayers[0]:
            for error in order:
                if error in final_error:
                    final_error[error]=final_error[error]+order[error]
                else:
                    final_error[error]=order[error]
        return final_error
    
    elif not bch_layerwise and not nonmarkovian:
        simplified_EOC_errors=dict()
        if bch_order == 1:
            for layer in fully_propagated_layers:
                for order in layer:
                    for error in order:
                        if error in simplified_EOC_errors:
                            simplified_EOC_errors[error]=simplified_EOC_errors[error]+order[error]
                        else:
                            simplified_EOC_errors[error]=order[error]

        else:
            Exception("Higher propagated through Errors are not Implemented Yet")
        return simplified_EOC_errors
    
    else:
        return fully_propagated_layers



def buildErrorlayers(circ,errorDict,qubits):
    ErrorGens=[]
    #For the jth layer of each circuit
    for j in range(circ.depth):
        l = circ.layer(j) # get the layer
        errorLayer=dict()
        for _, g in enumerate(l): # for gate in layer l
            gErrorDict = errorDict[g.name] #get the errors for the gate
            p1=qubits*'I' # make some paulis why?
            p2=qubits*'I'
            for errs in gErrorDict: #for an error in the accompanying error dictionary 
                errType=errs[0]
                paulis=[]
                for ind,el in enumerate(g): #enumerate the gate ind =0 is name ind = 1 is first qubit ind = 2 is second qubit
                    if ind !=0:  #if the gate element of concern is not the name
                        p1=p1[:el] + errs[1][ind-1] +p1[(el+1):]
                
                paulis.append(stim.PauliString(p1))
                if errType in "CA":
                    for ind,el in enumerate(g):
                        if ind !=0:
                            p2=p2[:el] + errs[2][ind-1] +p2[(el+1):]
                    paulis.append(stim.PauliString(p2))     
                errorLayer[_LSE(errType,paulis)]=gErrorDict[errs]
        ErrorGens.append([errorLayer])
    return ErrorGens
'''

Inputs:
_______
err_layer (list of dictionaries)
following_layer (list of dictionaries)
bch_order:

'''
def BCH_Handler(err_layer,following_layer,bch_order):         
    new_errors=[]
    for curr_order in range(0,bch_order):
        working_order=dict()
        #add first order terms into new layer
        if curr_order == 0:
            for error_key in err_layer[curr_order]:
                working_order[error_key]=err_layer[curr_order][error_key]
            for error_key in following_layer[curr_order]:
                working_order[error_key]=following_layer[curr_order[error_key]] 
            new_errors.append(working_order)

        elif curr_order ==1:
            working_order={}
            for error1 in err_layer[curr_order-1]:
                for error2 in following_layer[curr_order-1]:
                    errorlist = commute_errors(error1,error2,BCHweight=1/2*err_layer[error1]*following_layer[error2])
                    for error_tuple in errorlist:
                        working_order[error_tuple[0]]=error_tuple[1]
            if len(err_layer)==2:
                for error_key in err_layer[1]:
                    working_order[error_key]=err_layer[1][error_key]
            if len(following_layer)==2:
                for error_key in following_layer[1]:
                    working_order[error_key]=following_layer[1][error_key]
            new_errors.append(working_order)

        else:
            Exception("Higher Orders are not Implemented Yet")
    return new_errors

# There's a factor of a half missing in here. 
def nm_propagators(corr, Elist,qubits):
    Kms = []
    for idm in range(len(Elist)):
        Am=zeros([4**qubits,4**qubits],dtype=complex128)
        for key in Elist[idm][0]:
            Am += key.toWeightedErrorBasisMatrix()
            # This assumes that Elist is in reverse chronological order
        partials = []
        for idn in range(idm, len(Elist)):
            An=zeros([4**qubits,4**qubits],dtype=complex128)
            for key2 in Elist[idn][0]:
                An = key2.toWeightedErrorBasisMatrix()
            partials += [corr[idm,idn] * Am @ An]
        partials[0] = partials[0]/2
        Kms += [sum(partials,0)]
    return Kms

def averaged_evolution(corr, Elist,qubits):
    Kms = nm_propagators(corr, Elist,qubits)
    return multi_dot([expm(Km) for Km in Kms])