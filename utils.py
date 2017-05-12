"""
Утилиты логгирования и конфигурирования

log - интерфейс логгирования, если необходимы расширенные функции, переинициализировать во внешнем модуле
cfg - интерфейс считывания конфигурационного файла
get_options() - функция считывания параметров конфигурации
"""
import configparser
import logging

log = logging
cfg = None


def _init_config(conf_file):
    """
    Инициализирует экземпляр парсера конфигурации cfg

    :param conf_file: string, имя файла конфигурации
    :return: bool, True - если открыт и прочитан, False - в случае ошибки
    """
    global cfg

    cfg = configparser.ConfigParser()
    try:
        if not cfg.read(conf_file, 'utf-8'):
            log.critical('Конфигурационный файл не загружен')
            return
    except configparser.ParsingError as e:
        log.critical('Ошибка парсинга конфигурационного файла\n%s' % e.message)
        return

    return True


def get_options(section, options, conf_file='config.ini'):
    """
    Считывает параметры из конфигурационного файла

    Всегда считываются параметры host, user и password

    :param section: string, секция из которой будут считываться параметры
    :param options: [string], параметры для считывания, по умолчанию пусто
    :param conf_file: string, имя файла конфигурации
    :return: [string] or string, считанные параметры или None в случае ошибки чтения любого из параметров
    """
    if not cfg:
        if not _init_config(conf_file):
            return [None] * len(options)

    result_list = []

    if not isinstance(options, list):
        options = [options]

    for option in options:
        try:
            result_list.append(cfg.get(section, option))
        except configparser.NoSectionError as e:
            log.error('Секция %s не найдена' % e.section)
            return [None] * len(options)

        except configparser.NoOptionError as e:
            log.error('Параметр %s в секции %s не найден' % (e.option, e.section))
            return [None] * len(options)

    if len(result_list) == 1:
        return result_list[0]
    else:
        return result_list
