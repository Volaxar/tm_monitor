"""
Пакет пересылки сообщений из почтовых ящиков в телеграм. Часть системы мониторинга.

Глобальные переменные модуля:
 bot - экземпляр бота Telegram
 db - shelve хранилища
 
"""
import email
import imaplib
import logging
import re
import shelve

from telebot import TeleBot, types

import utils
from logger import DiffFileHandler
from utils import log, get_options

bot = None
db = None


def _conn_data():
    return get_options('main', ['host', 'domain', 'password'])


def _parse_command(message):
    """
    Обработка команд
    
    :param message: сообщение сс командой
    :return: bool, True - сообщение обработано, False - ошибка обработки
    """
    if message.text[1:].lower() == 'привет':
        if str(message.from_user.id) not in db:
            keyboard = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
            button_phone = types.KeyboardButton(text='Отправить номер телефона', request_contact=True)
            keyboard.add(button_phone)
            bot.send_message(message.chat.id, 'Привет! Скажи мне свой номер телефона', reply_markup=keyboard)
        else:
            bot.send_message(message.chat.id, 'Ага, я тоже рад тебя видеть')
    else:
        return
    
    return True


def _parse_contact(message):
    """
    Обработка контактов, добавление нового контакта в список авторизованных
    
    :param message: сообщение с контактной информацией
    :return: bool, True - сообщение обработано, False - ошибка обработки
    """
    # Проверяем, чтобы пользователь послал свои контактные данные
    if message.contact.user_id == message.from_user.id:
        host, domain, password = _conn_data()

        if not all([host, domain, password]):
            log.critical('В файле настроек параметры host, domain или password не найдены')
            return

        phone = str(message.contact.phone_number)
        
        # Проверяем существование почтового ящика, должен быть настроен заранее на почтовом сервере
        box = imaplib.IMAP4(host)
        data = box.login('%s@%s' % (phone, domain), password)
        box.logout()
        
        if data[0] == 'OK':
            phones_list = db.get('phones_list', [])

            if phone not in phones_list:
                phones_list.append(phone)
                
                db['phones_list'] = phones_list
            
            if phone not in db:
                db[phone] = message.chat.id
                db[str(message.from_user.id)] = db[phone]
                
                keyboard_hider = types.ReplyKeyboardRemove()
                bot.send_message(message.chat.id, 'Хорошо, я тебя запомнил', reply_markup=keyboard_hider)
            
            else:
                bot.send_message(message.chat.id, 'Виделись уже :)')
        else:
            bot.send_message(message.chat.id, 'Я тебя не узнаю!')
    else:
        bot.send_message(message.chat.id, 'Я сказал свой!')
    
    return True


def telegram_processing():
    """
    Обработка сообщений от пользователей телеграм.
    
    Обрабатывается команда "Привет", в ответ бот запрашивает номер телефона.
    И сообщение с контактной информацией, если номер телефона совпадает с существующим
    почтовым ящиком, пользователь помечается как авторизованный.
    
    """
    update_id = db.get('update_id', 0)  # ИД последнего полученного сообщения
    
    updates = bot.get_updates(update_id + 1, timeout=0)
    
    for update in updates:
        message = update.message
        
        if message.content_type == 'text' and message.text[0] == '/':
            if not _parse_command(message):
                log.warning('Не удалось обработать команду: %s' % message.text)
            
        elif message.content_type == 'contact':
            if not _parse_contact(message):
                log.warning('Не удалось обработать контакт: %s %s' %
                            (message.contact.first_name, message.contact.last_name))
        
        else:
            log.warning('Не удалось обработать сообщение: %s' % message)
        
        update_id = update.update_id
    
    db['update_id'] = update_id


def mail_processing():
    """
    Обработка входящих писем.
    
    """
    phones_list = db.get('phones_list', [])

    if not phones_list:
        return

    host, domain, password = _conn_data()

    if not all([host, domain, password]):
        log.critical('В файле настроек параметры host, domain или password не найдены')
        return

    xfrom, content_type = get_options('main', ['xfrom', 'content-type'])
    
    if not all([xfrom, content_type]):
        log.critical('В файле настроек параметры xfrom или content-type не найдены')
        return

    # Проходим по списку зарегистрированных номеров телефонов
    for phone in phones_list:
        box = imaplib.IMAP4(host)
        result = box.login('%s@%s' % (phone, domain), password)
        
        if result[0] == 'OK':
            box.select()
            
            chat_id = db.get(phone, None)
            
            typ, data = box.search(None, 'ALL')
            
            if typ == 'OK':
                
                for num in data[0].split():
                    try:
                        typ, data = box.fetch(num, '(RFC822)')
                        
                        mail = email.message_from_bytes(data[0][1])
    
                        box.store(num, '+FLAGS', '\\Deleted')
    
                        if mail.get('From') != xfrom or mail.get_content_type() != content_type:
                            continue
    
                        msg_body = mail.get_payload(decode=True)
                        charset = re.search(r'=(.*)', mail.get('Content-Type')).group(1)
    
                        msg_body = msg_body.decode(charset)
    
                        bot.send_message(chat_id, msg_body)
                    except Exception as e:
                        log.critical(e)

                box.expunge()
            else:
                log.error('Не удалось получить список писем с сервера')
            
            box.close()
        else:
            log.error('Не удалось подключиться к почтовому ящику: %s@%s' % (phone, domain))
        
        box.logout()


def main():
    """
    Инициализация логгера, бота и хранилища. Обработка почтовых сообщений  и сообщений от telegram.
    
    """
    global bot, db
    
    logger = logging.getLogger('tm_monitor')
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter('[%(asctime)s] %(levelname)-8s %(filename)s[LINE:%(lineno)d]# %(message)s')

    handler = DiffFileHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    utils.log = logger

    token = get_options('main', 'token')
    if not token:
        log.critical('В файле настроек токен бота не найден')
        return
    
    bot = TeleBot(token)

    db = shelve.open('data')

    telegram_processing()
    mail_processing()

    db.close()

if __name__ == '__main__':
    main()
