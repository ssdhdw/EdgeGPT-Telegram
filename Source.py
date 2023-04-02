import os
import asyncio
from telebot import TeleBot
from telebot.types import ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
from threading import Thread
from time import sleep
from EdgeGPT import Chatbot, ConversationStyle
from ImageGen import ImageGen

bot = TeleBot(os.environ['TOKEN'])
users_chatbots = {}  #pairs chat_id - bot

cookie = [{
    "name": "_U",
    "value": os.environ['COOKIE'],
    "domain": ".bing.com",
    "hostOnly": False,
    "path": "/",
    "secure": True,
    "httpOnly": False,
    "sameSite": "no_restriction",
    "session": False,
    "firstPartyDomain": "",
    "partitionKey": None,
    "expirationDate": 1681489175,
    "storeId": None
}]


def create_markup(suggests, requetst_left):
    markup = ReplyKeyboardMarkup(resize_keyboard=True,
                                 one_time_keyboard=True,
                                 input_field_placeholder=requetst_left)
    for i in suggests:
        markup.row(i["text"])
    return markup


def parse_message(text):
    text = text.replace("<",
                        " &lt; ").replace(">",
                                          " &gt; ").replace("&", " &amp; ")
    if text.startswith("[1]: "):
        text = text.split("\n\n")
        rows = text[0].split("\n")
        del text[0]
        links = []
        for i in rows:
            i = i.split()
            link = i[1]
            del i[0]
            del i[0]
            links.append([link, " ".join(i)])
        replace_elements = []
        text = "\n\n".join(text)
        for i in range(len(text) - 5):
            if text[i:i + 2] == "[^" and text[i + 3:i + 5] == "^]":
                replace_elements.append(text[i:i + 8])
        for i in replace_elements:
            index = int(i[2:3]) - 1
            if len(links) < index:
                continue
            text = text.replace(
                i,
                f' <a href="{links[index][0]}"><em>({links[index][1]})</em></a>'
            )
        while text.count("**") > 1:
            text = text.replace("**", "<b>", 1).replace("**", "</b>", 1)
        while text.count("```") > 1:
            text = text.replace("```", "<pre>", 1).replace("```", "</pre>", 1)
    return text


def generate_image(chat_id, prompt, reply_to_message_id=None):

    still_send_action = True

    def send_action():
        while still_send_action:
            sleep(1)
            bot.send_chat_action(chat_id, "upload_photo")

    temp_message = bot.send_message(
        chat_id,
        "_Genetaring image\\.\nThis might take a while_",
        parse_mode="MarkdownV2",
        reply_to_message_id=reply_to_message_id)
    action_thread = Thread(target=send_action)
    action_thread.start()
    try:
        image_generator = ImageGen(auth_cookie=os.environ['COOKIE'],
                                   quiet=True)
        imagesUrl = image_generator.get_images(prompt)
        media = []
        for i in imagesUrl:
            media.append(InputMediaPhoto(media=i))
        print(imagesUrl)
        still_send_action = False
        action_thread.join()
        bot.send_media_group(chat_id,
                             media,
                             reply_to_message_id=reply_to_message_id)
    except Exception as ex:
        bot.send_message(chat_id, f"Error: {ex}")
    finally:
        still_send_action = False
        bot.delete_message(chat_id, message_id=temp_message.id)


def stop_conversation(chat_id, text):
    if chat_id in users_chatbots.keys():
        chatbot = users_chatbots[chat_id]
        chatbot.close()
        del users_chatbots[chat_id]
    bot.send_message(chat_id, text=text, reply_markup=ReplyKeyboardRemove())


async def conversation_stream(chat_id, prompt):
    message = bot.send_message(chat_id,
                               "_You asked Bing to find information for you_",
                               parse_mode="MarkdownV2")
    chat_bot = users_chatbots[chat_id]

    buffer = ""
    update = True

    def update_message():
        old_buffer = ""
        while update:
            if old_buffer != buffer and buffer != "":
                bot.edit_message_text(buffer,
                                      message_id=message.id,
                                      chat_id=chat_id,
                                      parse_mode="HTML")
                bot.send_chat_action(chat_id, "typing")
                old_buffer = buffer
                sleep(0.4)
            sleep(0.1)

    update_thread = Thread(target=update_message)
    update_thread.start()

    async for final, response in chat_bot.ask_stream(
            prompt=prompt, conversation_style=ConversationStyle.creative):
        if final:
            update = False
            update_thread.join()
            return (response, message.id)
        buffer = parse_message(response)


def conversation_handler(chat_id, text):
    if len(text) > 2000:
        message_id = bot.send_message(chat_id, "Your message is too long")
    result, message_id = asyncio.run(conversation_stream(chat_id, text))
    result = result["item"]

    if result["result"]["value"] == "Success":
        requetst_left = f'{result["throttling"]["numUserMessagesInConversation"]}/{result["throttling"]["maxNumUserMessagesInConversation"]}'
        if len(result["messages"]) < 2:
            bot.send_message(chat_id,
                             "_But no one answered_",
                             parse_mode="MarkdownV2",
                             reply_markup=ReplyKeyboardRemove())
            return
        markup = ReplyKeyboardRemove()
        if "suggestedResponses" in result["messages"][1].keys():
            markup = create_markup(result["messages"][1]["suggestedResponses"],
                                   requetst_left)
        response_text = result["messages"][1]["adaptiveCards"][0]["body"][0][
            "text"]
        response_text = parse_message(response_text)

        try:
            bot.edit_message_text(text=response_text,
                                  chat_id=chat_id,
                                  message_id=message_id,
                                  parse_mode="HTML")
        except Exception:
            pass
        if len(result["messages"]
               ) > 2 and result["messages"][2]["contentType"] == "IMAGE":
            generate_image(chat_id,
                           result["messages"][2]["text"],
                           message_id=message_id)
        bot.send_message(chat_id=chat_id,
                         text=requetst_left,
                         reply_markup=markup)
        if result["throttling"]["numUserMessagesInConversation"] == result[
                "throttling"]["maxNumUserMessagesInConversation"]:
            stop_conversation(
                chat_id,
                "You have reached message limit!\nConversation restarted")
    else:
        bot.send_message(chat_id, text="Request wasn't success")


def command_handler(message):
    if message.text == "/start":
        bot.send_message(
            message.chat.id,
            "Hello, i am chat bot from Edge.\nSend me a question, and i will answer you."
        )
    elif message.text == "/restart":
        stop_conversation(message.chat.id, "Conversation restarted")
    elif message.text.startswith("/image"):
        prompt = message.text.split()
        del prompt[0]
        prompt = " ".join(prompt).strip()
        if prompt == "":
            bot.send_message(message.chat.id, "Usage:\n/image <prompt>")
            return
        generate_image(message.chat.id, prompt, message.id)


block_list = []


@bot.message_handler(content_types=["text"])
def message_handler(message):
    if message.chat.id in block_list:
        bot.send_message(message.chat.id,
                         text="Try again in few seconds",
                         reply_to_message_id=message.id)
        return
    else:
        block_list.append(message.chat.id)
    if message.text[0] == "/":
        command_handler(message)
    else:
        if message.chat.id in users_chatbots.keys():
            conversation_handler(message.chat.id, message.text)
        else:
            chatbot = Chatbot(cookies=cookie)
            users_chatbots.update({message.chat.id: chatbot})
            conversation_handler(message.chat.id, message.text)
    block_list.remove(message.chat.id)

if __name__ == "__main__":
    bot.polling()
