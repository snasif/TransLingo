# mypy: disable-error-code=import

"""Basic functionality for a WhatsApp chatbot.

This module contains the class definition to create Chatbot objects, each of
which can support one group of subscribers on WhatsApp. It also contains an
instance of such a chatbot for import by the Flask app.

Classes:
    SubscribersInfo -- A TypedDict to describe a subscriber to the group chat
    Chatbot -- A class to keep track of data about a group chat and its
        associated WhatsApp bot
"""

import json
import os
from types import SimpleNamespace
from typing import Dict, List, TypedDict

import requests
from cryptography.fernet import Fernet
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from language_data import LangData, translate_to

consts = SimpleNamespace()
# Constant strings for bot commands
consts.TEST = "/test"  # test translate
consts.ADD = "/add"  # add user
consts.REMOVE = "/remove"  # remove user
consts.ADMIN = "/admin"  # toggle admin vs. user role for user
consts.LIST = "/list"  # list all users
consts.LANG = "/lang"  # set language for user
# Roles for users in JSON file
consts.USER = "user"  # can only execute test translation command
consts.ADMIN = "admin"  # can execute all slash commands but cannot remove super
consts.SUPER = "super"  # can execute all slash commands, no limits
consts.VALID_ROLES = [consts.USER, consts.ADMIN, consts.SUPER]

pm_char = "#"  # Example: #xX_bob_Xx Hey bob, this is a private message!


class SubscribersInfo(TypedDict):
    """A TypedDict to describe a subscriber.

    For use as the values in a subscribers member of a Chatbot instance, the
    keys to which are to be strings of WhatsApp contact information of the form
    "whatsapp:<phone number with country code>".
    """
    name: str  # user's display name
    lang: str  # user's preferred language code
    role: str  # user's privilege level, "user", "admin", or "super"


class Chatbot:
    """The chatbot logic.

    Class variables:
        commands -- List of slash commands for the bot
        languages -- Data shared by all chatbots on the server about the
            languages supported by LibreTranslate

    Instance variables:
        client -- Client with which to access the Twilio API
        number -- Phone number the bot texts from
        json_file -- Path to a JSON file containing subscriber data
        subscribers -- Dictionary containing the data loaded from the file
        display_names -- Dictionary mapping display names to WhatsApp numbers
            for subscribers
        twilio_account_sid -- Account SID for the Twilio account
        twilio_auth_token -- Twilio authorization token
        twilio_number -- Bot's registered Twilio number

    Methods:
        process_msg -- Process a message to the bot
    """
    commands = [
        consts.TEST,
        consts.ADD,
        consts.REMOVE,
        consts.ADMIN,
        consts.LIST,
        consts.LANG]
    """All slash commands for the bot."""

    languages: LangData | None = None
    """Data for all languages supported by LibreTranslate."""

    def __init__(
            self,
            account_sid: str,
            auth_token: str,
            number: str,
            json_file: str = "subscribers.json",
            backup_file: str = "subscribers_bak.json",
            key_file: str = "subscribers_key.key",
            logs_file: str = "logs.json",
            backup_logs_file: str = "logs_bak.json",
            logs_key_file: str = "logs_key.key"):
        """Create the ChatBot object and populate class members as needed.

        Arguments:
            account_sid -- Account SID
            auth_token -- Account auth token
            number -- Phone number the bot texts from, including country
                extension
            json_file -- Path to a JSON file containing subscriber data
            backup_file -- Path to a JSON file containing backup data for the
                above JSON file
            key_file -- Path to a file containing the encryption key
            logs_file -- Path to a JSON file containing logs data
            backup_logs_file -- Path to a JSON file containing backup data for the
                above JSON file
            logs_key_file -- Path to a file containing the encryption key
        """
        # TODO: above needs to be changed to the doc style currently in the 260
        # branch (note key word args)
        if Chatbot.languages is None:
            Chatbot.languages = LangData()
        self.client = Client(account_sid, auth_token)
        self.number = number
        self.json_file = f"json/{json_file}"
        self.backup_file = f"json/{backup_file}"
        self.key_file = f"json/{key_file}"
        self.logs_file = f"json/{logs_file}"
        self.backup_logs_file = f"json/{backup_logs_file}"
        self.logs_key_file = f"json/{logs_key_file}"
        self.twilio_account_sid = account_sid
        self.twilio_auth_token = auth_token
        self.twilio_number = number
        with open(self.json_file, "rb") as file:
            encrypted_data = file.read()
        with open(self.key_file, "rb") as file:
            self.key = file.read()  # Retrieve encryption key
        f = Fernet(self.key)
        try:
            unencrypted_data = f.decrypt(encrypted_data).decode("utf-8")
            self.subscribers: Dict[str, SubscribersInfo] = json.loads(
                unencrypted_data)
        except BaseException:  # Handle corrupted file
            # TODO: Print message to server logs file that original file is
            # corrupted...recent data may not have been saved.
            with open(self.backup_file, "rb") as file:
                backup_encrypted_data = file.read()
            backup_unencrypted_data = f.decrypt(
                backup_encrypted_data).decode("utf-8")
            self.subscribers = json.loads(backup_unencrypted_data)
        self.display_names: Dict[str, str] = {
            v["name"]: k for k, v in self.subscribers.items()}

        with open(self.logs_file, "rb") as file:
            encrypted_logs_data = file.read()
        with open(self.logs_key_file, "rb") as file:
            self.key2 = file.read()  # Retrieve encryption key
        f = Fernet(self.key2)
        try:
            unencrypted_logs_data = f.decrypt(
                encrypted_logs_data).decode("utf-8")
            # TODO: Put unecrypted data into dictionary
            self.logs = json.loads(unencrypted_logs_data)
        except BaseException:  # Handle corrupted file
            # TODO: Print message to server logs file that original file is
            # corrupted...recent data may not have been saved.
            with open(self.backup_logs_file, "rb") as file:
                backup_encrypted_logs_data = file.read()
            backup_unencrypted_logs_data = f.decrypt(
                backup_encrypted_logs_data).decode("utf-8")
            # TODO: Put unecrypted data into dictionary
            self.logs = json.loads(backup_unencrypted_logs_data)

    def _reply(self, msg_body: str) -> str:
        """Reply to a message to the bot.

        Arguments:
            msg_body -- Contents to reply with

        Returns:
            A string suitable for returning from a route function.
        """
        resp = MessagingResponse()
        msg = resp.message()
        msg.body(msg_body)
        return str(resp)

    def _push(
            self,
            text: str,
            sender: str,
            media_urls: List[str]) -> str:
        """Push a translated message and media to one or more recipients.

        Arguments:
            text -- Contents of the message
            sender -- Sender"s WhatsApp contact info
            media_urls -- a list of media URLs to send, if any

        Returns:
            An empty string to the sender, or else an error message if the
                request to the LibreTranslate API times out or has some other
                error.
        """
        translations: Dict[str, str] = {}  # cache previously translated values
        for s in self.subscribers.keys():
            if s != sender:
                if self.subscribers[s]["lang"] in translations:
                    translated = translations[self.subscribers[s]["lang"]]
                else:
                    try:
                        translated = translate_to(
                            text, self.subscribers[s]["lang"])
                    except (TimeoutError, requests.HTTPError) as e:
                        return str(e)
                    translations[self.subscribers[s]["lang"]] = translated
                msg = self.client.messages.create(
                    from_=f"whatsapp:{self.number}",
                    to=s,
                    body=translated,
                    media_url=media_urls)
                print(msg.sid)
        return ""

    def _query(
            self,
            msg: str,
            sender: str,
            sender_lang: str,
            recipient: str,
            media_urls: List[str]) -> str:
        """Send a private message to a single recipient.

        Arguments:
            msg -- message contents
            sender -- sender display name
            sender_lang -- sender preferred language code
            recipient -- recipient display name
            media_urls -- any attached media URLs from Twilio's CDN

        Returns:
            An empty string to the sender, or else an error message if the
                request to the LibreTranslate API times out or has some other
                error.
        """
        # Check whether recipient exists
        if recipient not in self.display_names:
            return Chatbot.languages.get_unfound_err(  # type: ignore [union-attr]
                sender_lang)
        if not (msg == "" and len(media_urls) == 0):  # something to send
            recipient_contact = self.display_names[recipient]
            recipient_lang = self.subscribers[recipient_contact]["lang"]
            text = f"Private message from {sender}:\n{msg}"
            try:
                translated = translate_to(text, recipient_lang)
            except (TimeoutError, requests.HTTPError) as e:
                return str(e)
            pm = self.client.messages.create(
                from_=f"whatsapp:{self.number}",
                to=recipient_contact,
                body=translated,
                media_url=media_urls)
            print(pm.sid)
        return ""

    def _test_translate(self, msg: str, sender: str) -> str:
        """Translate a string to a language, then to a user"s native language.

        Arguments:
            msg -- message to translate
            sender -- number of the user requesting the translation

        Returns:
            The translated message, or else an error message if the request to
                the LibreTranslate API times out or has some other error.
        """
        sender_lang = self.subscribers[sender]["lang"]
        try:
            l = msg.split()[1].lower()
            if l not in Chatbot.languages.codes:  # type: ignore [union-attr]
                return Chatbot.languages.get_test_example(  # type: ignore [union-attr]
                    sender_lang)
        except IndexError:
            return Chatbot.languages.get_test_example(  # type: ignore [union-attr]
                sender_lang)
        # Translate to requested language then back to native language
        text = " ".join(msg.split()[2:])
        if text != "":
            try:
                translated = translate_to(text, l)
                return translate_to(translated, sender_lang)
            except (TimeoutError, requests.HTTPError) as e:
                return str(e)
        return Chatbot.languages.get_test_example(  # type: ignore [union-attr]
            sender_lang)

    def _add_subscriber(self, msg: str, sender_contact: str) -> str:
        """Add a new subscriber to the dictionary and save it to the JSON file.

        Arguments:
            msg -- the message sent to the bot
            sender_contact -- WhatsApp contact info of the sender

        Returns:
            A string suitable for returning from a Flask route endpoint.
        """
        sender_lang = self.subscribers[sender_contact]["lang"]

        # Split the message into parts
        parts = msg.split()

        # Check if there are enough arguments
        if len(parts) == 5:
            new_contact = parts[1]
            new_name = parts[2]
            new_lang = parts[3]
            new_role = parts[4]

            # Check if the phone number is valid
            if (not new_contact.startswith("+")
                ) or (not new_contact[1:].isdigit()):
                return Chatbot.languages.get_add_phone_err(  # type: ignore [union-attr]
                    sender_lang)

            new_contact_key = f"whatsapp:{new_contact}"
            # Check if the user already exists
            if new_contact_key in self.subscribers:
                return Chatbot.languages.get_exists_err(  # type: ignore [union-attr]
                    sender_lang)

            # Check if the display name is untaken
            if new_name in self.display_names:
                return Chatbot.languages.get_add_name_err(  # type: ignore [union-attr]
                    sender_lang)

            # Check if the language code is valid
            if new_lang not in\
                    Chatbot.languages.codes:  # type: ignore [union-attr]
                return Chatbot.languages.get_add_lang_err(  # type: ignore [union-attr]
                    sender_lang)

            # Check if the role is valid
            if new_role not in consts.VALID_ROLES:
                return Chatbot.languages.get_add_role_err(  # type: ignore [union-attr]
                    sender_lang)

            self.subscribers[new_contact_key] = {
                "name": new_name,
                "lang": new_lang,
                "role": new_role
            }
            self.display_names[new_name] = new_contact_key

            # Save the updated subscribers to subscribers.json
            # Convert the dictionary of subscribers to a formatted JSON string
            subscribers_list = json.dumps(self.subscribers, indent=4)
            # Create byte version of JSON string
            subscribers_list_byte = subscribers_list.encode("utf-8")
            f = Fernet(self.key)
            encrypted_data = f.encrypt(subscribers_list_byte)
            with open(self.json_file, "wb") as file:
                file.write(encrypted_data)

            # Copy data to backup file
            with open(self.json_file, 'rb') as fileone, open(self.backup_file, 'wb') as filetwo:
                for line in fileone:
                    filetwo.write(line)

            return Chatbot.languages.get_add_success(  # type: ignore [union-attr]
                sender_lang)
        else:
            return Chatbot.languages.get_add_err(  # type: ignore [union-attr]
                sender_lang)

    def _remove_subscriber(self, msg: str, sender_contact: str) -> str:
        """
        Remove a subscriber from the dictionary and save the updated dictionary.

        to the JSON file.

        Arguments:
            msg -- the message sent to the bot
            sender_contact -- WhatsApp contact info of the sender

        Returns:
            A string suitable for returning from a Flask route endpoint,
                indicating the result of the removal attempt.
        """
        sender_lang = self.subscribers[sender_contact]["lang"]
        sender_role = self.subscribers[sender_contact]["role"]

        # Split the message into parts
        parts = msg.split()

        # Check if there are enough arguments
        if len(parts) == 2:
            user_contact = parts[1]
            user_contact_key = f"whatsapp:{user_contact}"

            # Prevent sender from removing themselves
            # sender_contact = 2345678900 and user_contact = +12345678900
            # TODO: Need a way to fix this.
            if sender_contact == user_contact:
                return Chatbot.languages.get_remove_self_err(  # type: ignore [union-attr]
                    sender_lang)

            # Check if the user exists
            if user_contact_key not in self.subscribers:
                return Chatbot.languages.get_unfound_err(  # type: ignore [union-attr]
                    sender_lang)

            # Check if the sender has the necessary privileges
            if sender_role == consts.ADMIN and self.subscribers[
                    user_contact_key]["role"] == consts.SUPER:
                return Chatbot.languages.get_remove_super_err(  # type: ignore [union-attr]
                    sender_lang)
            else:
                name = self.subscribers[user_contact_key]["name"]
                del self.display_names[name]
                del self.subscribers[user_contact_key]

            # Save the updated subscribers to subscribers.json
            # Convert the dictionary of subscribers to a formatted JSON string
            subscribers_list = json.dumps(self.subscribers, indent=4)
            # Create byte version of JSON string
            subscribers_list_byte = subscribers_list.encode("utf-8")
            f = Fernet(self.key)
            encrypted_data = f.encrypt(subscribers_list_byte)
            with open(self.json_file, "wb") as file:
                file.write(encrypted_data)

            # Copy data to backup file
            with open(self.json_file, 'rb') as fileone, open(self.backup_file, 'wb') as filetwo:
                for line in fileone:
                    filetwo.write(line)

            return Chatbot.languages.get_remove_success(  # type: ignore [union-attr]
                sender_lang)
        else:
            return Chatbot.languages.get_remove_err(  # type: ignore [union-attr]
                sender_lang)

    def process_msg(
            self,
            msg: str,
            sender_contact: str,
            media_urls: List[str]) -> str:
        """Process a bot command.

        Arguments:
            msg -- the message sent to the bot
            sender_contact -- the WhatsApp contact info of the sender
            media_urls -- a list of media URLs sent with the message, if any

        Returns:
            A string suitable for returning from a Flask route endpoint.
        """
        try:
            sender = self.subscribers[sender_contact]
            sender_name = sender["name"]
            role = sender["role"]
            sender_lang = sender["lang"]
        except KeyError:
            return ""  # ignore; they aren't subscribed

        if not msg and len(media_urls) == 0:
            return ""  # ignore; nothing to send

        word_1 = msg.split()[0].lower() if msg else ""

        # PM someone:
        if word_1[0:1] == pm_char:
            split = msg.split()  # don't convert first word to lowercase
            pm_name = split[0][1:]  # display name without PM character
            return self._reply(
                self._query(
                    " ".join(split[1:]),
                    sender_name,
                    sender_lang,
                    pm_name,
                    media_urls))

        # Message group or /test as user:
        elif role == consts.USER:
            if word_1 == consts.TEST:  # test translate
                return self._reply(self._test_translate(msg, sender_contact))
            elif word_1[0:1] == "/" and len(word_1) > 1:
                return ""  # ignore invalid/unauthorized command
            else:  # just send a message
                text = sender_name + " says:\n" + msg
                self._push(text, sender_contact, media_urls)
                return ""  # say nothing to sender

        # Message group or perform any slash command as admin or superuser:
        else:
            match word_1:
                case consts.TEST:  # test translate
                    return self._reply(
                        self._test_translate(
                            msg, sender_contact))
                case consts.ADD:  # add user to subscribers
                    return self._reply(
                        self._add_subscriber(
                            msg, sender_contact))
                case consts.REMOVE:  # remove user from subscribers
                    return self._reply(
                        self._remove_subscriber(
                            msg, sender_contact))
                case consts.LIST:  # list all subscribers with their data
                    subscribers = json.dumps(self.subscribers, indent=2)
                    return self._reply(f"List of subscribers:\n{subscribers}")
                case _:  # just send a message
                    if word_1[0:1] == "/" and len(word_1) > 1:
                        return ""  # ignore invalid/unauthorized command
                    text = sender_name + " says:\n" + msg
                    return self._push(text, sender_contact, media_urls)


# Create bot (keyword args not provided because they have defaults)
TWILIO_ACCOUNT_SID: str = os.getenv(
    "TWILIO_ACCOUNT_SID")  # type: ignore [assignment]
TWILIO_AUTH_TOKEN: str = os.getenv(
    "TWILIO_AUTH_TOKEN")  # type: ignore [assignment]
TWILIO_NUMBER: str = os.getenv("TWILIO_NUMBER")  # type: ignore [assignment]
mr_botty = Chatbot(
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_NUMBER)
"""Global Chatbot object, of which there could theoretically be many."""
