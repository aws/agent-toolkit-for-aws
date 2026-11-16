from app import assistant, review

if __name__ == "__main__":
    print(assistant.reply("hello"), review.summarize("hello"))
