from agent.run_agent import run_agent


def main() -> None:
    state = run_agent("请帮我查询北京的天气", max_steps=5)
    print(state)


if __name__ == "__main__":
    main()
