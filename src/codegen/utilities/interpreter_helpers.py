"""This contains the helper methods used in interpreter generation."""
import collections
import re
from copy import deepcopy

from codegen.functions.function import Function
from codegen.utilities.function_helpers import to_param_argtype
from codegen.utilities.helpers import camel_to_snake_case

# This custom regex list doesn't split the string before the number.
INTERPRETER_CAMEL_TO_SNAKE_CASE_REGEXES = [
    re.compile("([^_\n])([A-Z][a-z]+)"),
    re.compile("([a-z])([A-Z])"),
    re.compile("([0-9])([^_0-9])"),
]

INTERPRETER_IGNORED_FUNCTIONS = [
    "GetExtendedErrorInfo",
    "GetArmStartTrigTimestampVal",
    "GetFirstSampTimestampVal",
    "GetRefTrigTimestampVal",
    "GetStartTrigTimestampVal",
    "GetTimingAttributeExTimestamp",
    "GetTimingAttributeTimestamp",
    "GetTrigAttributeTimestamp",
    "SetTimingAttributeExTimestamp",
    "SetTimingAttributeTimestamp",
    "SetTrigAttributeTimestamp",
    "GetArmStartTrigTrigWhen",
    "GetFirstSampClkWhen",
    "GetStartTrigTrigWhen",
    "GetSyncPulseTimeWhen",
    "SetArmStartTrigTrigWhen",
    "SetFirstSampClkWhen",
    "SetStartTrigTrigWhen",
    "SetSyncPulseTimeWhen",
]

LIBRARY_INTERPRETER_IGNORED_FUNCTIONS = [
    "RegisterSignalEvent",
    "RegisterEveryNSamplesEvent",
    "RegisterDoneEvent",
]


def get_interpreter_functions(metadata):
    """Converts the scrapigen metadata into a list of functions."""
    all_functions = deepcopy(metadata["functions"])
    functions_metadata = []
    for function_name, function_data in all_functions.items():
        if function_name in INTERPRETER_IGNORED_FUNCTIONS:
            continue
        function_data["c_function_name"] = function_name
        function_name = camel_to_snake_case(function_name, INTERPRETER_CAMEL_TO_SNAKE_CASE_REGEXES)
        function_name = function_name.replace("_u_int", "_uint")
        skippable_params = get_skippable_params_for_interpreter_func(function_data)
        function_data["parameters"] = (
            p for p in function_data["parameters"] if p["name"] not in skippable_params
        )
        functions_metadata.append(
            Function(
                function_name,
                function_data,
            )
        )

    return sorted(functions_metadata, key=lambda x: x._function_name)


def generate_interpreter_function_call_args(function_metadata):
    """Gets function call arguments."""
    # This implementation assumes that an array parameter is immediately followed
    # by the array size when making the c function call.
    function_call_args = []
    size_values = {}
    SizeParameter = collections.namedtuple("SizeParameter", ["name", "size"])
    for param in function_metadata.interpreter_parameters:
        if param.has_explicit_buffer_size:
            if param.direction == "in":
                size_values[param.size.value] = SizeParameter(
                    param.parameter_name, f"len({param.parameter_name})"
                )
            elif param.direction == "out":
                if param.size.mechanism == "ivi-dance":
                    size_values[param.size.value] = SizeParameter(param.parameter_name, "temp_size")

    for param in function_metadata.interpreter_parameters:
        if param.direction == "in":
            function_call_args.append(param.parameter_name)
        elif param.direction == "out":
            if param.has_explicit_buffer_size:
                function_call_args.append(param.parameter_name)
            else:
                function_call_args.append(f"ctypes.byref({param.parameter_name})")
        if param.has_explicit_buffer_size:
            if param.size.value in size_values:
                size_parameter = size_values[param.size.value]
                if param.parameter_name == size_parameter.name:
                    function_call_args.append(size_parameter.size)
    return function_call_args


def get_interpreter_parameter_signature(is_python_factory, params):
    """Gets parameter signature for function defintion."""
    params_with_defaults = []
    if not is_python_factory:
        params_with_defaults.append("self")
    for param in params:
        if param.type:
            params_with_defaults.append(param.parameter_name)

    return ", ".join(params_with_defaults)


def get_instantiation_lines_for_output(func):
    """Gets the lines of code for instantiation of output values."""
    instantiation_lines = []
    if func.is_init_method:
        instantiation_lines.append(f"task = lib_importer.task_handle(0)")
    for param in get_interpreter_output_params(func):
        if param.parameter_name == "task":
            continue
        elif param.repeating_argument:
            instantiation_lines.append(f"{param.parameter_name} = []")
        elif param.has_explicit_buffer_size:
            if (
                param.size.mechanism == "passed-in" or param.size.mechanism == "passed-in-by-ptr"
            ) and param.is_list:
                instantiation_lines.append(
                    f"{param.parameter_name} = numpy.zeros({param.size.value}, dtype={param.ctypes_data_type})"
                )
            elif param.size.mechanism == "custom-code":
                instantiation_lines.append(f"size = {param.size.value}")
                instantiation_lines.append(
                    f"{param.parameter_name} = numpy.zeros(size, dtype={param.ctypes_data_type})"
                )
        else:
            instantiation_lines.append(f"{param.parameter_name} = {param.ctypes_data_type}()")
    return instantiation_lines


def get_instantiation_lines_for_varargs(func):
    """Gets instantiation lines for functions with variable arguments."""
    instantiation_lines = []
    if any(get_varargs_parameters(func)):
        for param in func.output_parameters:
            instantiation_lines.append(
                f"{param.parameter_name}_element = {param.ctypes_data_type}()"
            )
            instantiation_lines.append(
                f"{param.parameter_name}.append({param.parameter_name}_element)"
            )
    return instantiation_lines


def get_argument_definition_lines_for_varargs(varargs_params):
    """Gets the lines for defining the variable arguments for a function."""
    argument_definition_lines = []
    for param in varargs_params:
        argtype = to_param_argtype(param)
        if param.direction == "in":
            argument_definition_lines.append(f"args.append({param.parameter_name}[index])")
        else:
            argument_definition_lines.append(
                f"args.append(ctypes.byref({param.parameter_name}_element))"
            )
        argument_definition_lines.append(f"argtypes.append({argtype})")
        argument_definition_lines.append("")
    return argument_definition_lines


def get_varargs_parameters(func):
    """Gets variable arguments of a function."""
    return [p for p in func.parameters if p.repeating_argument]


def get_interpreter_params(func):
    """Gets interpreter parameters for the function."""
    return (p for p in func.interpreter_parameters if p.direction == "in")


def get_grpc_interpreter_call_params(func, params):
    """Gets the interpreter parameters for grpc request."""
    compound_params = get_input_arguments_for_compound_params(func)
    grpc_params = []
    for param in params:
        if param.parameter_name not in compound_params:
            if param.is_enum:
                grpc_params.append(f"{param.parameter_name}_raw={param.parameter_name}")
            else:
                grpc_params.append(f"{param.parameter_name}={param.parameter_name}")
    grpc_params = sorted(list(set(grpc_params)))
    return ", ".join(grpc_params)


def get_skippable_params_for_interpreter_func(func):
    """Gets parameter names that needs to be skipped for the function."""
    skippable_params = []
    ignored_mechanisms = ["ivi-dance"]
    for param in func["parameters"]:
        size = param.get("size", {})
        if size.get("mechanism") in ignored_mechanisms:
            skippable_params.append(size.get("value"))
        if is_skippable_param(param):
            skippable_params.append(param["name"])
    return skippable_params


def is_skippable_param(param: dict) -> bool:
    """Checks whether the parameter can be skipped or not while generating interpreter."""
    ignored_params = ["size", "reserved"]
    if not param.get("include_in_proto", True) and (param["name"] in ignored_params):
        return True
    return False


def get_output_param_with_ivi_dance_mechanism(func):
    """Gets the output parameters with explicit buffer size."""
    output_parameters = get_output_params(func)
    explicit_output_params = [p for p in output_parameters if p.has_explicit_buffer_size]
    params_with_ivi_dance_mechanism = [
        p for p in explicit_output_params if p.size.mechanism == "ivi-dance"
    ]
    if len(params_with_ivi_dance_mechanism) > 1:
        raise NotImplementedError(
            "There is more than one output parameter with an explicit "
            "buffer size that follows ivi dance mechanism."
            "This cannot be handled by this template because it "
            'calls the C function once with "buffer_size = 0" to get the '
            "buffer size from the returned integer, which is normally an "
            "error code.\n\n"
            "Output parameters with explicit buffer sizes: {}".format(
                params_with_ivi_dance_mechanism
            )
        )

    if len(params_with_ivi_dance_mechanism) == 1:
        return params_with_ivi_dance_mechanism[0]
    return None


def has_parameter_with_ivi_dance_size_mechanism(func):
    """Returns true if the function has a parameter with ivi dance size mechanism."""
    parameter_with_size_buffer = get_output_param_with_ivi_dance_mechanism(func)
    return parameter_with_size_buffer is not None


def get_interpreter_output_params(func):
    """Gets the output parameters for the functions in interpreter."""
    return [p for p in func.interpreter_parameters if p.direction == "out"]


def get_output_params(func):
    """Gets output parameters for the function."""
    return [p for p in func.base_parameters if p.direction == "out"]


def get_return_values(func):
    """Gets the values to add to return statement of the function."""
    return_values = []
    for param in get_interpreter_output_params(func):
        if param.repeating_argument:
            return_values.append(
                f"[{param.parameter_name}_element.value for {param.parameter_name}_element in {param.parameter_name}]"
            )
        elif param.ctypes_data_type == "ctypes.c_char_p":
            return_values.append(f"{param.parameter_name}.value.decode('ascii')")
        elif param.is_list:
            return_values.append(f"{param.parameter_name}.tolist()")
        elif param.type == "TaskHandle":
            return_values.append(param.parameter_name)
        else:
            return_values.append(f"{param.parameter_name}.value")
    return return_values


def get_c_function_call_template(func):
    """Gets the template to use for generating the logic of calling the c functions."""
    if func.stream_response:
        return "/event_function_call.py.mako"
    elif any(get_varargs_parameters(func)):
        return "/exec_cdecl_c_function_call.py.mako"
    elif has_parameter_with_ivi_dance_size_mechanism(func):
        return "/double_c_function_call.py.mako"
    return "/default_c_function_call.py.mako"


def get_callback_param_data_types(params):
    """Gets the data types for call back function parameters."""
    return [p["ctypes_data_type"] for p in params]


def get_compound_parameter(params):
    """Returns the compound parameter associated with the given function."""
    return next((x for x in params if x.is_compound_type), None)


def get_input_arguments_for_compound_params(func):
    """Returns a list of input parameter for creating the compound parameter."""
    compound_params = []
    if any(x for x in func.base_parameters if x.is_compound_type):
        for parameter in func.base_parameters:
            if parameter.direction == "in" and parameter.repeating_argument:
                compound_params.append(parameter.parameter_name)
    return compound_params


def create_compound_parameter_request(func):
    """Gets the input parameters for createing the compound type parameter."""
    parameters = []
    compound_parameter_type = ""
    for parameter in func.base_parameters:
        if parameter.direction == "in" and parameter.repeated_var_args:
            compound_parameter_type = parameter.grpc_type.replace("repeated ", "")
            break

    for parameter in get_input_arguments_for_compound_params(func):
        parameters.append(f"{parameter}={parameter}[index]")
    return f"grpc_types.{compound_parameter_type}(" + ", ".join(parameters) + ")"


def get_response_parameters(output_parameters: list):
    """Gets the list of parameters in grpc response."""
    response_parameters = []
    for parameter in output_parameters:
        if not parameter.repeating_argument:
            response_parameters.append(f"response.{parameter.parameter_name}")
    return ", ".join(response_parameters)