#-------------------------------------------------------------------------------
#   Read output of gen_json.py and generate C# language bindings.
#
#   C# coding style:
#   - everything is PascalCase
#-------------------------------------------------------------------------------
import gen_ir
import json, re, os, shutil

module_names = {
    'sg_':      'Gfx',
    'sapp_':    'App',
    'stm_':     'Time',
    'saudio_':  'Audio',
    'sgl_':     'Gl',
    'sdtx_':    'DebugText',
    'sshape_':  'Shape',
}

c_source_paths = {
    'sg_':      'sokol-csharp/src/sokol/c/sokol_gfx.c',
    'sapp_':    'sokol-csharp/src/sokol/c/sokol_app.c',
    'stm_':     'sokol-csharp/src/sokol/c/sokol_time.c',
    'saudio_':  'sokol-csharp/src/sokol/c/sokol_audio.c',
    'sgl_':     'sokol-csharp/src/sokol/c/sokol_gl.c',
    'sdtx_':    'sokol-csharp/src/sokol/c/sokol_debugtext.c',
    'sshape_':  'sokol-csharp/src/sokol/c/sokol_shape.c',
}

name_ignores = [
    'sdtx_printf',
    'sdtx_vprintf',
    'sg_install_trace_hooks',
    'sg_trace_hooks',
]

name_overrides = {
    'sgl_error':    'sgl_get_error',   # 'error' is reserved in Zig
    'sgl_deg':      'sgl_as_degrees',
    'sgl_rad':      'sgl_as_radians',
    'sapp_isvalid': 'sapp_is_valid',
    'lock':         'dolock',
    'params':       'parameters',
    'sshape_element_range': 'sshape_make_element_range',
    'sshape_mat4':  'sshape_make_mat4',
}

# NOTE: syntax for function results: "func_name.RESULT"
type_overrides = {
    'sg_context_desc.color_format':         'int',
    'sg_context_desc.depth_format':         'int',
    'sg_apply_uniforms.ub_index':           'uint32_t',
    'sg_draw.base_element':                 'uint32_t',
    'sg_draw.num_elements':                 'uint32_t',
    'sg_draw.num_instances':                'uint32_t',
    'sshape_element_range_t.base_element':  'uint32_t',
    'sshape_element_range_t.num_elements':  'uint32_t',
    'sdtx_font.font_index':                 'uint32_t',
}

prim_types = {
    'int':          'int',
    'bool':         'bool',
    'char':         'byte',
    'int8_t':       'sbyte',
    'uint8_t':      'byte',
    'int16_t':      'short',
    'uint16_t':     'ushort',
    'int32_t':      'int',
    'uint32_t':     'uint',
    'int64_t':      'long',
    'uint64_t':     'ulong',
    'float':        'float',
    'double':       'double',
    'uintptr_t':    'nuint',
    'intptr_t':     'nint',
    'size_t':       'nuint'
}

prim_defaults = {
    'int':          '0',
    'bool':         'false',
    'int8_t':       '0',
    'uint8_t':      '0',
    'int16_t':      '0',
    'uint16_t':     '0',
    'int32_t':      '0',
    'uint32_t':     '0',
    'int64_t':      '0',
    'uint64_t':     '0',
    'float':        '0.0f',
    'double':       '0.0',
    'uintptr_t':    '0',
    'intptr_t':     '0',
    'size_t':       '0'
}

struct_types = []
enum_types = []
enum_items = {}
out_lines = ''

def reset_globals():
    global struct_types
    global enum_types
    global enum_items
    global out_lines
    struct_types = []
    enum_types = []
    enum_items = {}
    out_lines = ''

re_1d_array = re.compile("^(?:const )?\w*\s\*?\[\d*\]$")
re_2d_array = re.compile("^(?:const )?\w*\s\*?\[\d*\]\[\d*\]$")

def l(s):
    global out_lines
    out_lines += s + '\n'

def as_zig_prim_type(s):
    return prim_types[s]

# prefix_bla_blub(_t) => (dep.)BlaBlub
def as_zig_struct_type(s, prefix):
    parts = s.lower().split('_')
    outp = '' if s.startswith(prefix) else f'{parts[0]}.'
    for part in parts[1:]:
        if (part != 't'):
            outp += part.capitalize()
    return outp

# prefix_bla_blub(_t) => (dep.)BlaBlub
def as_zig_enum_type(s, prefix):
    parts = s.lower().split('_')
    outp = '' if s.startswith(prefix) else f'{parts[0]}.'
    for part in parts[1:]:
        if (part != 't'):
            outp += part.capitalize()
    return outp

def check_type_override(func_or_struct_name, field_or_arg_name, orig_type):
    s = f"{func_or_struct_name}.{field_or_arg_name}"
    if s in type_overrides:
        return type_overrides[s]
    else:
        return orig_type

def check_name_override(name):
    if name in name_overrides:
        return name_overrides[name]
    else:
        return name

def check_name_ignore(name):
    return name in name_ignores

# PREFIX_BLA_BLUB to bla_blub
def as_snake_case(s, prefix):
    outp = s.lower()
    if outp.startswith(prefix):
        outp = outp[len(prefix):]
    return outp

# prefix_bla_blub => BlaBlub
def as_pascal_case(s, prefix):
    if s.lower().startswith(prefix.lower()):
        s = s[len(prefix):]
    parts = s.lower().split('_')
    outp = parts[0].capitalize()
    for part in parts[1:]:
        outp += part.capitalize()
    return outp

# prefix_bla_blub => blaBlub
def as_camel_case(s):
    parts = s.lower().split('_')[1:]
    outp = parts[0]
    for part in parts[1:]:
        outp += part.capitalize()
    return outp

# PREFIX_ENUM_BLA => Bla, _PREFIX_ENUM_BLA => Bla
def as_enum_item_name(s):
    outp = s
    if outp.startswith('_'):
        outp = outp[1:]
    parts = outp.lower().split('_')[2:]
    outp = parts[0].capitalize()
    for part in parts[1:]:
        outp += part.capitalize()
    if outp[0].isdigit():
        outp = '_' + outp
    return outp

def enum_default_item(enum_name):
    return enum_items[enum_name][0]

def is_prim_type(s):
    return s in prim_types

def is_struct_type(s):
    return s in struct_types

def is_enum_type(s):
    return s in enum_types

def is_string_ptr(s):
    return s == "const char *"

def is_const_void_ptr(s):
    return s == "const void *"

def is_void_ptr(s):
    return s == "void *"

def is_const_prim_ptr(s):
    for prim_type in prim_types:
        if s == f"const {prim_type} *":
            return True
    return False

def is_prim_ptr(s):
    for prim_type in prim_types:
        if s == f"{prim_type} *":
            return True
    return False

def is_const_struct_ptr(s):
    for struct_type in struct_types:
        if s == f"const {struct_type} *":
            return True
    return False

def is_func_ptr(s):
    return '(*)' in s

def is_1d_array_type(s):
    return re_1d_array.match(s)

def is_2d_array_type(s):
    return re_2d_array.match(s)

def type_default_value(s):
    return prim_defaults[s]

def extract_array_type(s):
    return s[:s.index('[')].strip()

def extract_array_nums(s):
    return s[s.index('['):].replace('[', ' ').replace(']', ' ').split()

def extract_ptr_type(s):
    tokens = s.split()
    if tokens[0] == 'const':
        return tokens[1]
    else:
        return tokens[0]

def as_extern_c_arg_type(arg_type, prefix):
    if arg_type == "void":
        return "void"
    elif is_prim_type(arg_type):
        return as_zig_prim_type(arg_type)
    elif is_struct_type(arg_type):
        return as_zig_struct_type(arg_type, prefix)
    elif is_enum_type(arg_type):
        return as_zig_enum_type(arg_type, prefix)
    elif is_void_ptr(arg_type):
        return "void*"
    elif is_const_void_ptr(arg_type):
        return "void*"
    elif is_string_ptr(arg_type):
        return "byte*"
    elif is_const_struct_ptr(arg_type):
        return f"{as_zig_struct_type(extract_ptr_type(arg_type), prefix)}*"
    elif is_prim_ptr(arg_type):
        return f"{as_zig_prim_type(extract_ptr_type(arg_type))}*"
    elif is_const_prim_ptr(arg_type):
        return f"{as_zig_prim_type(extract_ptr_type(arg_type))}*"
    else:
        return '??? (as_extern_c_arg_type)'

def as_zig_arg_type(arg_prefix, arg_type, prefix):
    # NOTE: if arg_prefix is None, the result is used as return value
    pre = "" if arg_prefix is None else arg_prefix
    if arg_type == "void":
        if arg_prefix is None:
            return "void"
        else:
            return ""
    elif is_prim_type(arg_type):
        return as_zig_prim_type(arg_type) + pre
    elif is_struct_type(arg_type):
        return as_zig_struct_type(arg_type, prefix) + pre
    elif is_enum_type(arg_type):
        return as_zig_enum_type(arg_type, prefix) + pre
    elif is_void_ptr(arg_type):
        return "void*" + pre
    elif is_const_void_ptr(arg_type):
        return "void*" + pre
    elif is_string_ptr(arg_type):
        return "string" + pre
    elif is_const_struct_ptr(arg_type):
        # not a bug, pass const structs by value
        return f"in {as_zig_struct_type(extract_ptr_type(arg_type), prefix)}" + pre
    elif is_prim_ptr(arg_type):
        return f"ref {as_zig_prim_type(extract_ptr_type(arg_type))}" + pre
    elif is_const_prim_ptr(arg_type):
        return f"in {as_zig_prim_type(extract_ptr_type(arg_type))}" + pre
    else:
        return arg_prefix + "??? (as_zig_arg_type)"

# get C-style arguments of a function pointer as string
def funcptr_args_c(field_type, prefix):
    tokens = field_type[field_type.index('(*)')+4:-1].split(',')
    s = ""
    for token in tokens:
        arg_type = token.strip()
        if s != "":
            s += ", "
        c_arg = as_extern_c_arg_type(arg_type, prefix)
        if (c_arg == "void"):
            return ""
        else:
            s += c_arg
    return s

# get C-style result of a function pointer as string
def funcptr_res_c(field_type):
    res_type = field_type[:field_type.index('(*)')].strip()
    if res_type == 'void':
        return 'void'
    elif is_const_void_ptr(res_type):
        return 'void*'
    else:
        return '???'

def funcdecl_args_c(decl, prefix):
    s = ""
    func_name = decl['name']
    for param_decl in decl['params']:
        if s != "":
            s += ", "
        param_name = param_decl['name']
        param_type = check_type_override(func_name, param_name, param_decl['type'])
        s += as_extern_c_arg_type(param_type, prefix)
    return s

def funcdecl_args_zig(decl, prefix):
    s = ""
    func_name = decl['name']
    for param_decl in decl['params']:
        if s != "":
            s += ", "
        param_name = check_name_override(param_decl['name'])
        param_type = check_type_override(func_name, param_name, param_decl['type'])

        if is_string_ptr(param_type):
            s += "[M(U.LPUTF8Str)] "

        s += f"{as_zig_arg_type(f' {param_name}', param_type, prefix)}"
    return s

def funcdecl_result_c(decl, prefix):
    func_name = decl['name']
    decl_type = decl['type']
    result_type = check_type_override(func_name, 'RESULT', decl_type[:decl_type.index('(')].strip())
    return as_extern_c_arg_type(result_type, prefix)

def funcdecl_result_zig(decl, prefix):
    func_name = decl['name']
    decl_type = decl['type']
    result_type = check_type_override(func_name, 'RESULT', decl_type[:decl_type.index('(')].strip())
    zig_res_type = as_zig_arg_type(None, result_type, prefix)
    if zig_res_type == "":
        zig_res_type = "void"
    return zig_res_type

def gen_struct(decl, prefix):
    struct_name = decl['name']
    zig_type = as_zig_struct_type(struct_name, prefix)
    l(f"public struct {zig_type}")
    l("{")
    for field in decl['fields']:
        field_name = as_pascal_case(field['name'], "")
        field_type = field['type']
        field_type = check_type_override(struct_name, field_name, field_type)
        if field_type == "bool":
            l(f"    [M(U.I1)] public bool {field_name};")
        elif is_prim_type(field_type):
            l(f"    public {as_zig_prim_type(field_type)} {field_name};")
        elif is_struct_type(field_type):
            l(f"    public {as_zig_struct_type(field_type, prefix)} {field_name};")
        elif is_enum_type(field_type):
            l(f"    public {as_zig_enum_type(field_type, prefix)} {field_name};")
        elif is_string_ptr(field_type):
            l(f"    [M(U.LPUTF8Str)] public string {field_name};")
        elif is_const_void_ptr(field_type):
            l(f"    public void* {field_name};")
        elif is_void_ptr(field_type):
            l(f"    public void* {field_name};")
        elif is_const_prim_ptr(field_type):
            l(f"    public {as_zig_prim_type(extract_ptr_type(field_type))}* {field_name};")
        elif is_func_ptr(field_type):
            args = funcptr_args_c(field_type, prefix)
            if args != "":
                args += ", "
            l(f"    public delegate* unmanaged<{args}{funcptr_res_c(field_type)}> {field_name};")
        elif is_1d_array_type(field_type):
            array_type = extract_array_type(field_type)
            array_nums = extract_array_nums(field_type)
            if is_prim_type(array_type) or is_struct_type(array_type) or is_const_void_ptr(array_type):
                if is_prim_type(array_type):
                    zig_type = as_zig_prim_type(array_type)
                elif is_struct_type(array_type):
                    zig_type = as_zig_struct_type(array_type, prefix)
                elif is_enum_type(array_type):
                    zig_type = as_zig_enum_type(array_type, prefix)
                elif is_const_void_ptr(array_type):
                    zig_type = "IntPtr"
                else:
                    zig_type = '??? (array type)'
                l("    #pragma warning disable 169")
                l(f"    public struct {field_name}Collection")
                l("    {")
                l(f"        public ref {zig_type} this[int index] => ref MemoryMarshal.CreateSpan(ref _item0, {array_nums[0]})[index];")
                for i in range(0, int(array_nums[0])):
                    l(f"        private {zig_type} _item{i};")
                l("    }")
                l("    #pragma warning restore 169")

                l(f"    public {field_name}Collection {field_name};")
            else:
                l(f"//    FIXME: ??? array {field_name}: {field_type} => {array_type} [{array_nums[0]}]")
        elif is_2d_array_type(field_type):
            array_type = extract_array_type(field_type)
            array_nums = extract_array_nums(field_type)
            if is_prim_type(array_type):
                zig_type = as_zig_prim_type(array_type)
                def_val = type_default_value(array_type)
            elif is_struct_type(array_type):
                zig_type = as_zig_struct_type(array_type, prefix)
                def_val = ".{ }"
            else:
                zig_type = "???"
                def_val = "???"

            l("    #pragma warning disable 169")
            l(f"    public struct {field_name}Collection")
            l("    {")
            l(f"        public ref {zig_type} this[int x, int y] {{ get {{ fixed ({zig_type}* pTP = &_item0) return ref *(pTP + x + (y * {array_nums[0]})); }} }}")
            for i in range(0, int(array_nums[0]) * int(array_nums[1])):
                l(f"        private {zig_type} _item{i};")
            l("    }")
            l("    #pragma warning restore 169")

            l(f"    public {field_name}Collection {field_name};")

            #t0 = f"[{array_nums[0]}][{array_nums[1]}]{zig_type}"
            #l(f"    {field_name}: {t0} = [_][{array_nums[1]}]{zig_type}{{[_]{zig_type}{{ {def_val} }}**{array_nums[1]}}}**{array_nums[0]},")
        else:
            l(f"// FIXME: {field_name}: {field_type};")
    l("}")

def gen_consts(decl, prefix):
    for item in decl['items']:
        l(f"public const int {as_pascal_case(item['name'], prefix)} = {item['value']};")

def gen_enum(decl, prefix):
    l(f"public enum {as_zig_enum_type(decl['name'], prefix)}")
    l("{")
    for item in decl['items']:
        item_name = as_enum_item_name(item['name'])
        if item_name != "ForceU32":
            if 'value' in item:
                l(f"    {item_name} = {item['value']},")
            else:
                l(f"    {item_name},")
    l("}")

def gen_func_c(decl, prefix):
    l(f"[DllImport(\"sokol\", EntryPoint = \"{decl['name']}\")]")

def gen_func_zig(decl, prefix):
    c_func_name = decl['name']
    zig_func_name = as_pascal_case(check_name_override(decl['name']), prefix)
    zig_res_type = funcdecl_result_zig(decl, prefix)

    if zig_res_type == "string":
        l("[return:M(U.LPUTF8Str)]")

    l(f"public static extern {zig_res_type} {zig_func_name}({funcdecl_args_zig(decl, prefix)});")
    l("")

def pre_parse(inp):
    global struct_types
    global enum_types
    for decl in inp['decls']:
        kind = decl['kind']
        if kind == 'struct':
            struct_types.append(decl['name'])
        elif kind == 'enum':
            enum_name = decl['name']
            enum_types.append(enum_name)
            enum_items[enum_name] = []
            for item in decl['items']:
                enum_items[enum_name].append(as_enum_item_name(item['name']))

def gen_imports(inp, dep_prefixes):
    for dep_prefix in dep_prefixes:
        dep_module_name = module_names[dep_prefix]
        l(f'using {dep_prefix[:-1]} = Sokol.{dep_module_name};')
        l('')

def gen_module(inp, dep_prefixes):
    l('// machine generated, do not edit')
    l('using System;')
    l('using System.Runtime.InteropServices;')
    l('using M = System.Runtime.InteropServices.MarshalAsAttribute;')
    l('using U = System.Runtime.InteropServices.UnmanagedType;')
    l('')
    gen_imports(inp, dep_prefixes)
    pre_parse(inp)
    prefix = inp['prefix']
    l("namespace Sokol")
    l("{")
    l(f"public static unsafe partial class {inp['module']}")
    l("{")
    for decl in inp['decls']:
        if not decl['is_dep']:
            kind = decl['kind']
            if kind == 'consts':
                gen_consts(decl, prefix)
            elif not check_name_ignore(decl['name']):
                if kind == 'struct':
                    gen_struct(decl, prefix)
                elif kind == 'enum':
                    gen_enum(decl, prefix)
                elif kind == 'func':
                    gen_func_c(decl, prefix)
                    gen_func_zig(decl, prefix)
    l("}")
    l("}")

def prepare():
    print('Generating C# bindings:')
    if not os.path.isdir('sokol-csharp/src/sokol'):
        os.makedirs('sokol-csharp/src/sokol')
    if not os.path.isdir('sokol-csharp/src/sokol/c'):
        os.makedirs('sokol-csharp/src/sokol/c')

def gen(c_header_path, c_prefix, dep_c_prefixes):
    module_name = module_names[c_prefix]
    c_source_path = c_source_paths[c_prefix]
    print(f'  {c_header_path} => {module_name}')
    reset_globals()
    shutil.copyfile(c_header_path, f'sokol-csharp/src/sokol/c/{os.path.basename(c_header_path)}')
    ir = gen_ir.gen(c_header_path, c_source_path, module_name, c_prefix, dep_c_prefixes)
    gen_module(ir, dep_c_prefixes)
    output_path = f"sokol-csharp/src/sokol/{ir['module']}.cs"
    with open(output_path, 'w', newline='\n') as f_outp:
        f_outp.write(out_lines)
