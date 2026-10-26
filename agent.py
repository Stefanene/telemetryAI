from aos.api import AOS

# Workers come from AOS_WORKERS in .env (screen_worker.py:Screen) plus AOS's coding_agent.
aos = AOS.create("workspaces/desk", goal="Desktop assistant: look at the user's screen and help with everyday tasks")

if __name__ == "__main__":
    print(f"Workers: {', '.join(aos.workers)}")
    print("Give a goal, or start with '?' to ask about past work (empty line to quit).")
    while goal := input("\n> ").strip():
        if goal.startswith("?"):
            print(aos.ask(goal[1:].strip()))
        else:
            task = aos.run(goal)
            print(task.data["result"] or f"task {task.data['status']}")
