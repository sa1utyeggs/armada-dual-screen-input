"""Audit imported symbols against exact sources and the running kernel.

The original Armada package has no kernel-devel/Module.symvers. With
CONFIG_MODVERSIONS=n only, derive a *subset*, never invent missing exports or
CRCs. Every name must exist in live __ksymtab and have an unambiguous public
EXPORT_SYMBOL declaration in the matching patched source. This is not an ABI
proof: packages additionally require the exact config and kernel-notes digest.
"""
from pathlib import Path
import argparse
import json
import re
import subprocess


def collect(source, imported, live):
    missing = imported - live
    if missing:
        raise ValueError('Not exported by the running kernel: ' + ', '.join(sorted(missing)))
    declarations = {name: set() for name in imported}
    export = re.compile(r'\b(EXPORT_SYMBOL(?:_NS_GPL|_GPL|_NS)?)\s*\(\s*('
                        + '|'.join(re.escape(name) for name in sorted(imported))
                        + r')\s*(?:,\s*("[^"]*"|[A-Za-z_]\w*)\s*)?\)')
    for path in source.rglob('*'):
        if path.suffix not in ('.c', '.h', '.S') or not path.is_file():
            continue
        text = path.read_text(errors='replace')
        if 'EXPORT_SYMBOL' not in text:
            continue
        defaults = re.findall(r'^\s*#\s*define\s+DEFAULT_SYMBOL_NAMESPACE\s+"([^"]*)"',
                              text, re.M)
        for kind, name, explicit in export.findall(text):
            namespace = explicit.strip('"') if explicit else (defaults[0] if defaults else '')
            if explicit and not explicit.startswith('"'):
                raise ValueError('Unresolved namespace macro for ' + name)
            if len(set(defaults)) > 1:
                raise ValueError('Conditional namespaces need review: ' + str(path))
            tag = 'EXPORT_SYMBOL_GPL' if kind.endswith('GPL') else 'EXPORT_SYMBOL'
            declarations[name].add((tag, namespace))
    # core.c generates printk exports using this exact local macro. Check the
    # macro body and each invocation, rather than guessing that _dev_* exports
    # are public. The live-symbol check above remains mandatory.
    core = (source / 'drivers/base/core.c').read_text()
    macro = re.search(r'#define define_dev_printk_level\(func, kern_level\)(.*?)\n\n', core, re.S)
    if macro and 'EXPORT_SYMBOL(func);' in macro.group(1):
        for name in imported:
            if re.search(r'\bdefine_dev_printk_level\(\s*' + re.escape(name) + r'\s*,', core):
                declarations[name].add(('EXPORT_SYMBOL', ''))
    result, errors = {}, []
    for name, choices in declarations.items():
        if len(choices) != 1:
            errors.append('Missing/ambiguous source export for ' + name + ': ' + repr(choices))
            continue
        tag, namespace = next(iter(choices))
        result[name] = {'export': tag, 'namespace': namespace}
    if errors:
        raise ValueError('\n'.join(sorted(errors)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--object', type=Path, required=True)
    parser.add_argument('--live-exports', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    config = (args.kernel / '.config').read_text()
    if '# CONFIG_MODVERSIONS is not set' not in config:
        raise SystemExit('This subset workflow requires CONFIG_MODVERSIONS=n')
    names = {line.split()[-1] for line in subprocess.check_output(
        ['nm', '-u', str(args.object)], text=True).splitlines() if line.strip()}
    # modpost generates this module's own definition in <name>.mod.c.
    # It is not a reference to a function/data export from the host kernel.
    names.discard('__this_module')
    live = set(json.loads(args.live_exports.read_text()))
    result = collect(args.kernel, names, live)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'export-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    (args.out / 'Module.symvers').write_text(''.join(
        f'0x00000000\t{name}\tvmlinux\t{row["export"]}\t{row["namespace"]}\n'
        for name, row in sorted(result.items())))
    print(f'Audited {len(result)} imports against source and live export names')


if __name__ == '__main__':
    main()
