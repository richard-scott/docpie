import logging
import re
try:
    from itertools import product
except ImportError:
    # python < 2.6
    def product(*args, **kwds):
        # product('ABCD', 'xy') --> Ax Ay Bx By Cx Cy Dx Dy
        # product(range(2), repeat=3) --> 000 001 010 011 100 101 110 111
        pools = map(tuple, args) * kwds.get('repeat', 1)
        result = [[]]
        for pool in pools:
            result = [x+[y] for x in result for y in pool]
        for prod in result:
            yield tuple(prod)

from docpie.error import DocpieError, DocpieExit, DocpieException
from docpie.saver import Saver

logger = logging.getLogger('docpie.element')

try:
    StrType = basestring
except NameError:
    StrType = str
NoneType = type(None)


class Atom(object):
    # when stdopt=True, long option should only start with `--`
    # Otherwith, `-flag` is also long options
    # and `-flag=sth` will be considered as `-flag` and `=sth`
    # and attachopt won't work
    # and attachvalue is forced to be `True`
    stdopt = True
    attachopt = True    # `-rf` can stand for `-r -f`. Not for long options
    attachvalue = True    # `-rf` can stand for `-r f`. Not for long options

    # short option should not use `=`,
    # `-asth` equals `-a sth`, `-a=sth` equals `-a =sth`
    # long option can use
    flag_or_upper_re = re.compile(r'^(?P<hyphen>-{0,2})'
                                  r'($|[\da-zA-Z_][\da-zA-Z_\-]*$)')
    angular_bracket_re = re.compile(r'^<.*?>$')

    def __init__(self, *names, **kwargs):
        self._names = set(names)
        self._default = kwargs.get('default', None)
        self.value = None

    def set_alias(self, *names):
        logger.debug('set alias %s for %s' % (';'.join(names),
                                              ';'.join(self._names)))
        self._names.update(names)

    def set_default(self, value):
        self._default = value

    def _cache(get_class):
        cache_dic = {}

        def wrapped(klass, atom):
            if atom not in cache_dic:
                result = get_class(klass, atom)
                cache_dic[atom] = result
            return cache_dic[atom]

        return wrapped

    @classmethod
    @_cache
    def get_class(klass, atom):
        m = klass.flag_or_upper_re.match(atom)
        if m:
            match = m.groupdict()
            if match['hyphen']:
                return Option
            elif atom.isupper():
                return Argument
            else:
                return Command
        elif klass.angular_bracket_re.match(atom):
            return Argument
        else:
            logger.debug('I guess %s is a Command' % atom)
            return Command

    def arg_range(self):
        return [1]

    def has_name(self, *name):
        return self._names.intersection(name)

    def get_names(self):
        return self._names

    def get_option_name(self):
        return set()

    def fix(self):
        return self
    fix_nest = fix
    fix_empty = fix

    @property
    def repeat(self):
        return False

    def set_save_point(self):
        return self.value

    dump_value = set_save_point

    def load_save_point(self, value):
        self.value = value

    load_value = load_save_point

    @classmethod
    def convert_2_dict(cls, obj):
        return {
            '__class__': obj.__class__.__name__,
            'names': tuple(obj._names),
            'default': obj._default,
        }

    @classmethod
    def convert_2_object(cls, dic):
        names = dic['names']
        cls_name = dic['__class__']
        assert cls_name in ('Option', 'Command', 'Argument')
        if cls_name == 'Option':
            # raise NotImplementedError('call Option.convert_2_object instead')
            return Option.convert_2_object(dic)
        elif cls_name == 'Command':
            cls = Command
        elif cls_name == 'Argument':
            cls = Argument
        default = dic['default']
        # Not work on py2.6
        # return cls(*names, default=default)
        return cls(*names, **{'default': default})

    def __str__(self):
        return '/'.join(self._names)

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, ', '.join(self._names))

    def __eq__(self, other):
        if type(self) is not type(other):
            return False
        if not self.has_name(*other.get_names()):
            return False
        return True


class Option(Atom):
    long_re = re.compile(r'(?P<name>--[0-9a-zA-Z]*)(?P<eq>=?)(?P<value>.*)')

    def __init__(self, *names, **kwargs):
        # assert all(x.startswith('-') for x in names)
        super(Option, self).__init__(*names, **kwargs)
        self.ref = kwargs.get('ref', None)    # a instance, not a list
        # self.countable = False

    def get_value(self, in_repeat=False):
        # default = self._default
        names = self._names
        value = self.value
        ref = self.ref

        multi = (in_repeat or (value not in (True, False) and
                               not isinstance(value, StrType)))

        if ref is not None:
            max_value_num = -1 if in_repeat else max(ref.arg_range())
            multi = multi or (max_value_num > 1)
        else:
            max_value_num = 0

        if not value:  # False/None/0
            if max_value_num == 0:
                if value is None:
                    value = False
            elif max_value_num == 1:
                value = None
            else:
                value = []
            logger.debug('%s returns its value %s', self, value)
            # Not work on py2.6
            # return {name: value for name in names}
            result = {}
            for name in names:
                result[name] = value
            return result

        # has value, has ref
        if ref is not None:
            if max_value_num != 0:
                value = ref.get_flat_list_value()
                if max_value_num == 1:
                    assert len(value) < 2, value
                    value = value[0] if value else None

        # has value, no ref
        elif multi:
            if value is None:
                value = 0
            value = int(value)

        logger.debug('%s returns its value %s', self, value)
        # Not work on py2.6
        # return {name: value for name in names}
        result = {}
        for name in names:
            result[name] = value
        return result

    def get_sys_default_value(self, in_repeat=False):
        if in_repeat:
            value = []
        else:
            value = False
        # Not work on py2.6
        # return {name: value for name in self._names}
        result = {}
        for name in self._names:
            result[name] = value
        return result

    def match(self, argv, saver, repeat_match=False):
        current = argv.current()
        if current is None:
            logger.info('no argv left')
            return False

        if not repeat_match and self.value:
            logger.debug('%s already has a value', self)
            return True

        saver.save(self, argv)

        dash_index = argv.index('-') if '-' in argv else -1
        dashes_index = argv.index('--') if '--' in argv else -1

        # TODO: check if there is buggy
        if ('-' in self._names and
                dash_index != -1 and
                not (argv.auto_dashes and dashes_index < dash_index)):
            if repeat_match:
                if self.value is None:
                    self.value = 1
                else:
                    self.value += 1
            else:
                self.value = True
            argv.pop('-')
            argv.dash = True
            return True

        if ('--' in self._names and
                dashes_index != -1 and
                not argv.auto_dashes):
            if repeat_match:
                self.value += 1
            else:
                self.value = True
            argv.pop('--')
            argv.dashes = True
            return True

        find_it, sub_argv = \
            argv.break_for_option(self._names, Atom.stdopt, Atom.attachvalue)

        if not find_it:
            logger.debug('not found matching %s in %s', self, argv)
            saver.rollback(self, argv)
            return False

        if repeat_match:
            if self.value is None:
                self.value = 1
            else:
                self.value += 1
        else:
            self.value = True

        if self.ref is None:
            if sub_argv is not None:
                if Atom.stdopt and Atom.attachopt:
                    sub_argv[0] = '-' + sub_argv[0]
                    logger.debug("%s put %s pack to argv %s",
                                 self, sub_argv, argv)
                    argv[:0] = sub_argv
                    logger.debug('%s matched %s / %s', self, self.value, argv)
                    return True
                logger.debug("%s doesn't have ref but argv is %s",
                             self, sub_argv)
                return False
                # raise DocpieExit(DocpieException.usage_str)
            logger.debug('%s matched %s / %s', self, self.value, argv)
            return True

        result = self.ref.match(sub_argv or argv, saver, repeat_match)
        if sub_argv:
            logger.info('%s ref must fully match but failed for %s',
                        self, sub_argv)
            raise DocpieExit(DocpieException.usage_str)

        if not result:
            logger.debug('%s ref match failed %s', self, sub_argv or argv)
            saver.rollback(self, argv)
            return False
        logger.debug('%s matched %s / %s', self, self.value, argv)
        return True

    def get_option_name(self):
        return self.get_names()

    def reset(self):
        value = self.value
        if value is not None:
            if isinstance(value, int):
                self.value = 0
            else:
                self.value = False

        if self.ref is not None:
            self.ref.reset()

    # Note: this is kind of tricky:
    # make it different from Unit(Command, Unit())
    def dump_value(self):
        ref = self.ref
        return {'self': self.value,
                'ref': None if ref is None else ref.dump_value()}

    def load_value(self, value):
        self.value = value['self']
        if self.ref is not None:
            self.ref.load_value(value['ref'])

    def merge_value(self, values):
        opt_values = [each['self'] for each in values]
        ref_values = [each['ref'] for each in values]

        if len(opt_values) == 1:
            assert len(ref_values) == 1
            result = {'self': opt_values[0], 'ref': ref_values[0]}
        else:
            opt_value = sum(filter(None, opt_values))
            if all(x is None for x in ref_values):
                ref_value = None
            else:
                ref_value = self.ref.merge_value(ref_values)
            result = {'self': opt_value, 'ref': ref_value}
        return result

    @classmethod
    def convert_2_dict(cls, obj):
        ref = obj.ref
        result = super(Option, cls).convert_2_dict(obj)
        result['ref'] = (ref.convert_2_dict(ref) if ref is not None else None)
        return result

    @classmethod
    def convert_2_object(cls, dic):
        names = dic['names']
        cls_name = dic['__class__']
        assert cls_name == 'Option'
        default = dic['default']
        ref_value = dic['ref']
        ref = None if ref_value is None else Unit.convert_2_object(ref_value)
        # Not work on py2.6
        # return cls(*names, default=default, ref=ref)
        return cls(*names, **{'default': default, 'ref': ref})

    def __str__(self):
        result = super(Option, self).__str__()
        if self.ref:
            return '`%s %s`' % (result, self.ref)
        return '`%s`' % result

    def __repr__(self):
        return 'Option(%s, ref=%r)' % (', '.join(self._names), self.ref)

    def __eq__(self, other):
        if type(self) is not type(other):
            return False
        if not Atom.stdopt:
            equal = super(Option, self).__eq__(other)
        else:
            equal = self.get_option_name().intersection(
                        other.get_option_name())

        if equal:
            equal = (self.ref == other.ref)

        return equal


class Command(Atom):

    def __init__(self, *names, **kwargs):
        # assert all(self.type(x) == self.COMMAND for x in names)
        super(Command, self).__init__(*names, **kwargs)
        self.value = False

    def reset(self):
        self.value = False

    def match(self, argv, saver, repeat_match=False):
        current = argv.current()
        if current in (None, '-'):
            logger.debug('%s matching %s failed', self, current)
            return False

        if not repeat_match and self.value:
            logger.debug('%s already has a value %s', self, self.value)
            return True

        skip = 0
        if current == '--':
            if argv.auto_dashes and argv.dashes:
                current = argv.current(1)
                skip = 1
            else:
                logger.debug('%s matching %s failed', self, current)
                return False

        if current not in self._names or Atom.get_class(current) is Option:
            logger.debug('%s matching %s failed', self, current)
            return False

        if repeat_match:
            self.value += 1
        else:
            self.value = True

        saver.save(self, argv)
        argv.next(skip)
        logger.debug('%s matched %s/%s', self, self.value, argv)
        return True

    def merge_value(self, values):
        if len(values) == 1:
            return values[0]
        else:
            return sum(filter(None, values))

    def get_value(self, in_repeat=False):
        if in_repeat:
            value = int(self.value)
        else:
            value = self.value

        # Not work on py2.6
        # return {name: value for name in self._names}
        result = {}
        for name in self._names:
            result[name] = value
        return result

    def get_sys_default_value(self, in_repeat=False):
        if in_repeat:
            value = []
        else:
            value = False
        # Not work on py2.6
        # return {name: value for name in self._names}
        result = {}
        for name in self._names:
            result[name] = value
        return result


class Argument(Atom):

    def __init__(self, *names, **kwargs):
        super(Argument, self).__init__(*names, **kwargs)
        self.value = None

    def reset(self):
        if isinstance(self.value, list):
            self.value = []
        else:
            self.value = None

    def set_save_point(self):
        value = self.value
        if isinstance(value, list):
            return list(value)
        return value

    dump_value = set_save_point

    def match(self, argv, saver, repeat_match):
        current = argv.current()
        if current in (None, '-'):
            logger.debug('%s matching %s failed', self, current)
            return False

        if not repeat_match and (self.value is not None and self.value != []):
            logger.info('%s already has a value %s', self, self.value)
            return True

        if current == '--':
            if argv.auto_dashes and argv.dashes:
                current = argv.current(1)
                # nothing left
                if current is None:
                    logger.debug('argv %s ran out when matchins %s',
                                 argv, self)
                    return False
                # force to be command/arg
                if repeat_match:
                    if self.value is None:
                        self.value = [current]
                    else:
                        self.value.append(current)

                else:
                    self.value = current

                saver.save(self, argv)
                argv.next(1)
                logger.debug('%s matched %s/%s', self, self.value, argv)
                return True
            else:
                logger.debug('%s matching %s failed', self, current)
                return False

        # check if it's `--flag=sth`

        if current.startswith('--') and '=' in current:
            opt, value = current.split('=', 1)
            if Atom.get_class(opt) is Option:
                logger.debug('%s matching %s failed', self, current)
                return False

        if Atom.get_class(current) is Option:
            logger.debug('%s matching %s failed', self, current)
            return False

        if repeat_match:
            if self.value is None:
                self.value = [current]
            else:
                self.value.append(current)

        else:
            self.value = current

        saver.save(self, argv)
        argv.next()
        logger.debug('%s matched %s/%s', self, self.value, argv)
        return True

    def get_value(self, in_repeat=False):
        value = self.value
        if in_repeat:
            if value is None:
                value = []
            elif not isinstance(value, list):
                value = [value]
        # Not work on py2.6
        # return {name: value for name in self._names}
        result = {}
        for name in self._names:
            result[name] = value
        return result

    def get_sys_default_value(self, in_repeat=False):
        if in_repeat:
            value = []
        else:
            value = None
        # Not work on py2.6
        # return {name: value for name in self._names}
        result = {}
        for name in self._names:
            result[name] = value
        return result

    def merge_value(self, values):
        if len(values) == 1:
            return values[0]
        else:
            result = []
            for each in values:
                if each is None:
                    pass
                elif isinstance(each, list):
                    result.extend(each)
                else:
                    result.append(each)
            return result

    def __eq__(self, other):
        if isinstance(other, Argument):
            return True
        return False


class Unit(list):

    def __init__(self, *atoms, **kwargs):
        super(Unit, self).__init__(atoms)
        self.repeat = kwargs.get('repeat', False)

    def reset(self):
        for each in self:
            each.reset()

    def get_value(self, in_repeat=False):
        result = {}
        for each in self:
            this_result = each.get_value(in_repeat or self.repeat)
            repeated_keys = set(
                result.keys()).intersection(this_result.keys())
            for key in repeated_keys:
                old_value = result[key]
                new_value = this_result[key]
                if (key.startswith('-') and
                        any(
                            isinstance(
                                x,
                                (int, NoneType))
                            for x in (old_value, new_value))):
                    final_value = (old_value or 0) + (new_value or 0)
                elif all(isinstance(x, int) for x in (old_value, new_value)):
                    final_value = old_value + new_value
                else:
                    final_value = []
                    for each_value in (old_value, new_value):
                        if each_value is None:
                            pass
                        elif isinstance(each_value, list):
                            final_value.extend(each_value)
                        else:
                            final_value.append(each_value)
                logger.debug('merge %s value as %s', key, final_value)
                this_result[key] = final_value
            result.update(this_result)
        logger.debug('%s return value %s', self, result)
        return result

    def get_option_name(self):
        result = set()
        for each in self:
            result.update(each.get_option_name())
        return result

    def arg_range(self):
        if not self:
            return [0]

        all_range = (each.arg_range() for each in self)
        # all_range = list(all_range)
        producted = product(*all_range)
        # producted = list(producted)
        this_range = set(sum(x) for x in producted)

        if self.repeat:
            this_range.add(float('inf'))

        return list(this_range)

    def fix(self):
        if not self:
            return Optional()
        if len(self) == 1:
            return self._fix_single_element()
        else:
            return self._fix_multi_element()

    def fix_optional(self, opt_2_ins):
        result = []

        skip = 0
        for idx, element in enumerate(self):
            if skip > 0:
                skip -= 1
                continue
            if isinstance(element, OptionsShortcut):
                pass
            elif isinstance(element, (Unit, Either)):
                element.fix_optional(opt_2_ins)
            elif isinstance(element, Option):
                names = element.get_names()
                common_names = names.intersection(opt_2_ins)
                assert len(common_names) <= 1, "fixme: %s" % common_names
                if common_names:
                    ins_in_opt = opt_2_ins[common_names.pop()]
                    ref_in_opt = ins_in_opt.ref
                    if ref_in_opt is not None:
                        if self[idx + 1] == ref_in_opt:
                            element.ref = self[idx + 1]
                            logger.debug('%s set ref %s', element, element.ref)
                            skip = 1
                        else:
                            expect_num = len(ref_in_opt)
                            tried = Required(
                                *self[idx+1:idx+1+expect_num]).fix()
                            logger.debug('try %s == %s', ref_in_opt, tried)
                            if ref_in_opt == tried:
                                element.ref = tried
                                logger.debug('%s set ref %s',
                                             element, element.ref)
                                skip = expect_num
                            else:
                                raise DocpieError(
                                    "%s announced differently "
                                    "in usage(%s) and option(%s)" % (
                                        element, self, ins_in_opt))
            result.append(element)
        self[:] = result
        return self

    def _fix_single_element(self):
        this_element = self[0].fix()
        # None, Atom, Unit

        # None
        if this_element is None:
            return None

        # Atom, Unit
        self[:] = [this_element]

        # Unit
        if isinstance(this_element, Unit):
            return self.fix_nest()

        # Atom
        return self

    def _fix_multi_element(self):
        result = []
        for each in self:
            fixed = each.fix()
            if fixed is not None:
                result.append(fixed)
        if not result:
            return None

        self[:] = result
        if len(result) == 1:
            return self._fix_single_element()
        else:
            return self

    def fix_nest(self):
        assert len(self) == 1, '%s need not fix nest' % self
        if isinstance(self[0], Unit):
            repeat = self.repeat or self[0].repeat
            if type(self) is not type(self[0]):
                # Not work on py2.6
                # return Optional(*self[0], repeat=repeat).fix()
                return Optional(*self[0], **{'repeat': repeat}).fix()
            else:
                result = self[0]
                result.repeat = repeat
                return result.fix()
        return self

    def match_oneline(self, argv, saver):
        # Though it's one line matching
        # It still need to deal with situation like:
        # `-b cmd1 -a cmd2 -b`
        # to match argv like `-b -a cmd1 cmd2 -b` or `-b cmd1 -a cmd2 -b`
        # it still check the line more than once
        saver.save(self, argv)
        # logger.info('argv ran out when matching %s at %s', self, each)
        # need_match = list(self)
        old_status = None
        new_status = argv.status()
        matched_status = [isinstance(x, (Optional, OptionsShortcut))
                          for x in self]
        while old_status != new_status and argv:  # the token is moving

            old_status = new_status
            for index, each in enumerate(self):
                if not argv:
                    logger.debug('argv run out when matching %s', each)
                    break

                saver.save(each, argv)
                result = each.match(argv, saver, False)
                if result:
                    matched_status[index] = True
            new_status = argv.status()
        else:
            logger.debug('out of loop matching %s, argv %s', self, argv)
            if all(matched_status):
                logger.debug('%s matched', self)
                return True
            logger.debug('%s matching failed %s', self, matched_status)
            saver.rollback(self, argv)
            return False

    # TODO: balance the value for `<a>... <b>`
    def match_repeat(self, argv, saver):
        saver.save(self, argv)
        # logger.info('argv ran out when matching %s at %s', self, each)
        # need_match = list(self)
        old_status = None
        new_status = argv.status()
        full_match_count = 0
        history_values = []
        while old_status != new_status and argv:
            self.reset()
            # saver.save(self, argv)
            old_status = new_status
            result = self.match_oneline(argv, saver)
            if result:
                full_match_count += 1
            else:
                break
            history_values.append(self.dump_value())
            new_status = argv.status()

        logger.debug('matching %s %s time(s)', self, full_match_count)
        if full_match_count:
            merged_value = self.merge_value(history_values)
            self.load_value(merged_value)
        else:
            saver.rollback(self, argv)
        return full_match_count

    # TODO: check if this is buggy
    def merge_value(self, value_list):
        result = []
        for index, values in enumerate(zip(*value_list)):
            ins = self[index]
            result.append(ins.merge_value(values))
        return result

    def set_save_point(self):
        return None

    def load_save_point(self, value):
        pass

    def dump_value(self):
        return [x.dump_value() for x in self]

    def load_value(self, value):
        for each, v in zip(self, value):
            each.load_value(v)

    def get_flat_list_value(self):
        result = []
        for each in self:
            if hasattr(each, 'get_flat_list_value'):
                result.extend(each.get_flat_list_value())
            else:
                assert isinstance(each, Argument)
                value = each.value
                # acturally argument has no default so far
                # default = each._default
                if value is None:
                    pass
                elif isinstance(value, list):
                    result.extend(value)
                else:
                    result.append(value)
        return result

    def get_sys_default_value(self, in_repeat=False):
        result = {}
        if in_repeat or self.repeat:
            for each in self:
                result.update(each.get_sys_default_value(True))
            return result

        for each in self:
            this_result = each.get_sys_default_value(False)
            common_keys = set(result).intersection(this_result)
            for key in common_keys:
                old_value = result[key]
                new_value = this_result[key]
                if all(isinstance(x, int)
                        for x in (old_value, new_value)):
                    this_result[key] = old_value + new_value
                else:
                    this_result[key] = []
            result.update(this_result)
        return result

    @classmethod
    def convert_2_dict(cls, obj):
        return {
            '__class__': obj.__class__.__name__,
            'atoms': [x.convert_2_dict(x) for x in obj],
            'repeat': obj.repeat
        }

    @classmethod
    def convert_2_object(cls, dic):
        cls_name = dic['__class__']
        assert cls_name in ('Optional', 'Required')
        if cls_name == 'Optional':
            cls = Optional
        else:
            cls = Required
        atoms = (convert_2_object(x) for x in dic['atoms'])
        repeat = dic['repeat']
        # Not work on py2.6
        # return cls(*atoms, repeat=repeat)
        return cls(*atoms, **{'repeat': repeat})

    def __eq__(self, other):
        if not isinstance(other, Unit):
            return False

        # when one is None, this will work too
        if type(self) is not type(other):
            return False
        if len(self) != len(other):
            return False
        return all(ts == tt for ts, tt in zip(self, other))

    def __repr__(self):
        return '%s(%s%s)' % (self.__class__.__name__,
                             ', '.join(map(repr, self)),
                             ', repeat=True' if self.repeat else '')


class Required(Unit):

    def match(self, argv, saver, repeat_match=False):
        if not (repeat_match or self.repeat):
            logger.debug('try to match %s once, %s', self, argv)
            result = self.match_oneline(argv, saver)
            logger.debug('%s matching status: %s', self, result)
            return result
        logger.debug('try to match %s repeatedly', self)
        return bool(self.match_repeat(argv, saver))

    def __str__(self):
        return '(%s)%s' % (' '.join(map(str, self)),
                           '...' if self.repeat else '')


class Optional(Unit):

    def arg_range(self):
        this_range = super(Optional, self).arg_range()
        if 0 not in this_range:
            this_range.append(0)
        return this_range

    def match(self, argv, saver, repeat_match=False):
        repeat = repeat_match or self.repeat
        logging.debug('matching %s with %s%s',
                      self, argv, ', repeatedly' if repeat else '')
        func = (self.match_repeat if repeat else self.match_oneline)

        func(argv, saver)
        return True

    def __str__(self):
        if len(self) == 1:
            if isinstance(self[0], OptionsShortcut):
                if self.repeat:
                    return '[options]...'
                return '[options]'

            if isinstance(self[0], Atom) and self[0].has_name('options'):
                fmt = '[ %s ]%s'
            else:
                fmt = '[%s]%s'
        else:
            fmt = '[%s]%s'
        return fmt % (' '.join(map(str, self)), '...' if self.repeat else '')


class OptionsShortcut(object):
    _ref = None        # option instances (list)

    def __init__(self):
        self._hide = set()

    def get_option_name(self):
        raise AssertionError("fixme: Unexpected call")

    def set_hide(self, names):
        self._hide.update(names)

    def get_hide(self):
        return self._hide

    def need_hide(self, *name):
        return self._hide.intersection(name)

    def arg_range(self):
        logger.info('fixme: Unexpected call')
        return [0]

    # repeat_match will be ignored
    def match(self, argv, saver, repeat_match=False):
        hide = self._hide
        ref = self._ref
        logger.debug('[options]/%s/%s try matching %s', ref, hide, argv)
        for each in filter(lambda x: not hide.intersection(x._names), ref):
            if not argv:
                logger.info('argv run out before matching [options] %s(-%s)',
                            self._ref, self._hide)
                return True
            logger.debug('[options] try %s matching %s', each, argv)
            each.match(argv, saver, repeat_match)
        return True

    def get_value(self, in_repeat=False):
        hide = self._hide
        ref = self._ref
        result = {}  # developer should ensure no same options in [options]
        for each in filter(lambda x: not hide.intersection(x._names), ref):
            result.update(each.get_value(in_repeat))
        return result

    def get_sys_default_value(self, in_repeat=False):
        hide = self._hide
        ref = self._ref
        result = {}
        for each in filter(lambda x: not hide.intersection(x._names), ref):
            result.update(each.get_sys_default_value(in_repeat))
        return result

    def set_need_match(self):
        if self._ref is None:
            self._match_ref = ()
        if self._match_ref is None:
            self._match_ref = tuple(
                filter(lambda x: not self.need_hide(*x.get_names()), self._ref)
            )

    @classmethod
    def set_ref(klass, ref_lis):
        klass._ref = ref_lis

    @classmethod
    def reset(klass):
        assert False

    @property
    def repeat(self):
        return False

    def fix(self):
        return self

    def set_save_point(self):
        return None

    def load_save_point(self, value):
        pass

    def dump_value(self):
        return [x.dump_value() for x in self.ref]

    def load_value(self, value):
        for each, v in zip(self.ref, value):
            each.load_value(value)

    def merge_value(self, values):
        ref = self.ref
        result = []
        for index, value in enumerate(zip(values)):
            ins = ref[index]
            result.append(ins.merge_value(value))

        return result

    @classmethod
    def convert_2_dict(cls, obj):
        return {
            '__class__': obj.__class__.__name__,
            # 'ref': [x.convert_2_dict() for x in obj._ref],
            'hide': tuple(obj._hide),
        }

    @classmethod
    def convert_2_object(cls, dic):
        assert dic['__class__'] == 'OptionsShortcut'
        ins = OptionsShortcut()
        ins.set_hide(dic['hide'])
        return ins

    # TODO: better behavior
    def __eq__(self, other):
        if type(other) is OptionsShortcut:
            return True
        return False

    def __str__(self):
        return '[options]'

    def __repr__(self):
        return 'OptionsShortcut()'


# branch
class Either(list):

    def __init__(self, *branch):
        assert(all(isinstance(x, Unit) for x in branch))
        super(Either, self).__init__(branch)
        self.matched_branch = -1

    def reset(self):
        # for repeat loop, it needs to know which one is matched
        # so I don't reset the matched_branch
        # TODO: test if it's buggy
        # self.matched_branch = -1
        for each in self:
            each.reset()

    def get_option_name(self):
        result = set()
        for each in self:
            result.update(each.get_option_name())
        return result

    def fix(self):
        if not self:
            return None
        result = []
        for each in self:
            fixed = each.fix()
            if fixed is not None:
                result.append(fixed)
        if not result:
            return None
        self[:] = result
        return self.fix_argument_only()

    def fix_argument_only(self):
        '''
        fix_argument_only() -> Either or Unit(Argument)
        `<arg> | ARG | <arg3>` ->
            `Required(Argument('<arg>', 'ARG', '<arg3>'))`
        `[<arg>] | [ARG] | [<arg3>]` ->
            `Optional(Argument('<arg>', 'ARG', '<arg3>'))`
        `(<arg>) | [ARG]` -> not change, return self
        `-a | --better` -> not change
        '''
        # for idx, branch in enumerate(self):
        #     if isinstance(branch[0], Either):
        #         self[idx] = branch.fix()
        first_type = type(self[0])
        if first_type not in (Required, Optional):
            return self
        for branch in self:
            if not (len(branch) == 1 and
                    isinstance(branch, first_type) and
                    isinstance(branch[0], Argument)):
                logger.debug('fix %r not change', self)
                return self
        else:
            first = self[0][0]
            for each in self:
                first.set_alias(*each[0].get_names())
            result = first_type(first)
            logger.debug('fix %r -> %r', self, result)
            return result

    def match_oneline(self, argv, saver):
        if self.matched_branch != -1:
            branch = self[self.matched_branch]
            return branch.match(argv, saver, False)

        # do not need saver, when failed, just reset
        # saver.save(self, argv)
        saver = Saver()
        for index, each in enumerate(self):
            clone_argv = argv.clone()
            logger.debug('try matching %s in %s', each, argv)
            result = each.match(clone_argv, saver, False)
            if result:
                self.matched_branch = index
                argv.set_by(clone_argv)
                return True
        # saver.del_save(self)
        self.reset()
        return False

    def match_repeat(self, argv, saver):
        at_least_once = False
        if self.matched_branch == -1:
            result = self.match_oneline(self, argv, saver)
            if not result:
                return False
            at_least_once = True

        return self.matched_branch.match(argv, saver, True) or at_least_once

    def match(self, argv, saver, repeat_match):
        if not repeat_match:
            logger.debug('try matching %s once in %s', self, argv)
            return self.match_oneline(argv, saver)
        logger.debug('try matching %s repeatedly in %s', self, argv)
        return self.match_repeat(argv, saver)

    def set_save_point(self):
        return self.matched_branch

    def load_save_point(self, value):
        self.matched_branch = value

    def dump_value(self):
        matched_branch = self.matched_branch
        assert matched_branch != -1, 'fixme'
        return self[matched_branch].dump_value()

    def merge_value(self, values):
        matched_branch = self.matched_branch
        assert matched_branch != -1, 'fixme'
        return self[matched_branch].merge_value(values)

    def arg_range(self):
        result = set()
        for each in self:
            result.update(each.arg_range())
        return list(result)

    def load_value(self, value):
        matched_branch = self.matched_branch
        assert matched_branch != -1, 'fixme'
        self[matched_branch].load_value(value)

    def get_flat_list_value(self):
        if self.matched_branch == -1:
            return []
        current = self[self.matched_branch]
        return current.get_flat_list_value()

    def get_value(self, in_repeat=False):
        if self.matched_branch != -1:
            rest = list(self)
            value_dict = rest.pop(self.matched_branch).get_value(in_repeat)
            rest_dict = [x.get_sys_default_value(in_repeat) for x in rest]
        else:
            value_dict = {}
            rest_dict = [x.get_sys_default_value(in_repeat) for x in self]

        for dft_dict in rest_dict:
            common_keys = set(value_dict).intersection(dft_dict)
            for key in common_keys:
                valued = value_dict[key]
                default = dft_dict[key]
                if all(isinstance(x, int) for x in (valued, default)):
                    dft_dict[key] = valued + default
                elif None in (valued, default):
                    dft_dict[key] = valued if default is None else default
                else:
                    result = []
                    for each in (valued, default):
                        if each is None:
                            pass
                        elif isinstance(each, list):
                            result.extend(each)
                        else:
                            result.append(each)
                    dft_dict[key] = result
            value_dict.update(dft_dict)
        return value_dict

    def get_sys_default_value(self, in_repeat=False):
        rest = [x.get_sys_default_value(in_repeat) for x in self]
        result = rest.pop()

        for rest_dict in rest:
            common_keys = set(result).intersection(rest_dict)
            for key in common_keys:
                old = result[key]
                new = rest_dict[key]

                if all(isinstance(x, bool) for x in (old, new)):
                    result[key] = bool(old + new)
                elif any(isinstance(x, int) for x in (old, new)):
                    result[key] = bool(old + new)
                elif any(isinstance(x, list) for x in (old, new)):
                    result[key] = []
                else:
                    assert old is new is None, 'fixme'
                    result[key] = None

            result.update(rest_dict)

        return result

    def fix_optional(self, opt_2_ins):
        self[:] = (x.fix_optional(opt_2_ins) for x in self)
        return self

    @classmethod
    def convert_2_dict(cls, obj):
        return {
            '__class__': obj.__class__.__name__,
            'branch': [x.convert_2_dict() for x in obj],
        }

    @classmethod
    def convert_2_object(cls, dic):
        assert dic['__class__'] == 'Either'
        branch = (convert_2_object(x) for x in dic['branch'])
        return Either(*branch)

    def __eq__(self, other):
        if not isinstance(other, (Either, Argument)):
            return False

        # if isinstance(self, Argument) and isinstance(other, Argument):
        #     return self == other
        if len(self) != len(other):
            return False

        # it is not a good way to check equal
        # because the order of each branch is not important
        return all(ts == tt for ts, tt in zip(self, other))

    def __str__(self):
        return ' | '.join(map(str, self))

    def __repr__(self):
        return 'Either(%s)' % ', '.join(map(repr, self))


def convert_2_dict(obj):
    return obj.convert_2_dict(obj)


def convert_2_object(dic):
    cls_name = dic['__class__']
    if cls_name in ('Argument', 'Command', 'Option'):
        return Atom.convert_2_object(dic)
    elif cls_name in ('Optional', 'Required'):
        return Unit.convert_2_object(dic)
    elif cls_name == 'OptionsShortcut':
        return OptionsShortcut.convert_2_object(dic)
    elif cls_name == 'Either':
        return Either.convert_2_object(dic)
    else:
        raise ValueError('%s can not be converted to object', dic)
