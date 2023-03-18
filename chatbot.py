"""Basic functionality for a WhatsApp chatbot.

This module contains the class definition to create Chatbot objects, each of
which can support one group of subscribers on WhatsApp. It also contains an
instance of such a chatbot for import by the Flask app.
"""

import json
import os
from types import SimpleNamespace
from typing import Dict, List

from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

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
# Languages
consts.CZECH = "czech"
consts.ENGLISH = "english"
consts.SPANISH = "spanish"
consts.UKRANIAN = "ukranian"


class Chatbot:
    """The chatbot logic.

    Class variables:
        commands -- List of slash commands for the bot

    Instance variables:
        client -- Client with which to access the Twilio API
        number -- Phone number the bot texts from
        json_file -- Path to a JSON file containing subscriber data
        subscribers -- Dictionary containing the data loaded from the file

    Methods:
        reply -- Reply to a message to the bot
        push -- Push a message to one or more recipients given their numbers
        process_cmd -- Process a slash command and send a reply from the bot
    """

    commands = [
        consts.TEST,
        consts.ADD,
        consts.REMOVE,
        consts.ADMIN,
        consts.LIST,
        consts.LANG]

    languages = [consts.CZECH, consts.ENGLISH, consts.SPANISH, consts.UKRANIAN]

    test_err = "".join([
        "Please provide a valid language to test with. Example:\n" +
        "\t/test spanish Hello everybody!\nValid languages:"
    ] + list(map(lambda l: ("\n" + l.capitalize()), languages)))

    def __init__(
            self,
            account_sid: str,
            auth_token: str,
            number: str,
            json_file: str = "bot_subscribers/template.json"):
        """Create the ChatBot object.

        Arguments:
            account_sid -- Account SID
            auth_token -- Account auth token
            number -- Phone number the bot texts from, including country
                extension
            json_file -- Path to a JSON file containing subscriber data
        """
        self.client = Client(account_sid, auth_token)
        self.number = number
        self.json_file = json_file
        with open(json_file, encoding="utf-8") as file:
            self.subscribers = json.load(file)

    def reply(self, msg_body: str) -> str:
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

    def push(self, msg_body: str, recipients: List[str]):
        """Push a message to one or more recipients given their numbers.

        Arguments:
            msg_body -- Contents of the message
            recipients -- List of recipients' WhatsApp contact info (see key in
                bot_subscribers/template.json for an example of how these are
                formatted)
        """
        for r in recipients:
            msg = self.client.messages.create(
                from_=f"whatsapp:{self.number}",
                to=r,
                body=msg_body)
            print(msg.sid)

    @staticmethod
    def translate_to(msg: str, lang: str) -> str:
        # TODO: translate to given language
        return ""

    @staticmethod
    def test_translate(msg: str, sender: Dict[str, str]):
        """Translate a string to a language, then to a user's native language.

        Arguments:
            msg -- message to translate
            sender -- user requesting the translation

        Returns:
            The translated message.
        """
        try:
            lang = msg.split()[1].lower()
            if lang not in Chatbot.languages:
                return Chatbot.test_err
        except IndexError:
            return Chatbot.test_err
        # Translate to requested language then back to native language
        translated = Chatbot.translate_to(
            "".join(msg.split()[2:]), lang)
        return Chatbot.translate_to(translated, sender["lang"])

    def process_msg(
            self,
            msg: str,
            sender_contact: str,
            sender_name: str) -> str:
        """Process a bot command.

        Arguments:
            msg -- the message sent to the bot
            sender_contact -- the WhatsApp contact info of the sender
            sender_name -- the WhatsApp profile name of the sender

        Returns:
            A string suitable for returning from a Flask route endpoint.
        """
        try:
            sender = self.subscribers[sender_contact]
            role = sender["role"]
        except KeyError:
            return ""  # ignore; they aren't subscribed

        word_1 = msg.split()[0].lower()
        if role == consts.USER:
            if word_1 == consts.TEST:  # test translate
                return Chatbot.test_translate(msg, sender)
            else:  # just send a message
                # TODO:
                pass
        else:
            match word_1:
                case consts.TEST:  # test translate
                    return Chatbot.test_translate(msg, sender)
                case consts.ADD:  # add user to subscribers
                    # TODO:
                    pass
                case consts.REMOVE:  # remove user from subscribers
                    # TODO:
                    pass
                case consts.ADMIN:  # toggle user -> admin or admin -> user
                    # TODO:
                    pass
                case consts.LIST:  # list all subscribers with their data
                    # TODO:
                    pass
                case consts.LANG:  # change preferred language of user
                    # TODO:
                    pass
                case _:  # just send a message
                    pass  # TODO:
        return ""  # TODO: whatever is returned is sent to user who sent command


mr_botty = Chatbot(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN"),
    os.getenv("TWILIO_NUMBER"))  # TODO: add subscriber JSON file
"""Global Chatbot object, of which there could theoretically be many."""