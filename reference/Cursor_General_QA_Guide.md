# Guide: Using Cursor AI for General Q&A (Without Git Clutter)

You mentioned that using the web-based Cursor Agent (`cursor.com/agents`) creates unnecessary Git branches and commits for simple questions. This is because the Web Agent is designed specifically for **asynchronous coding tasks** that result in Pull Requests, not for synchronous, general conversation.

Here is the recommended workflow to use Cursor with Gemini 3 Pro for general questions without polluting your GitHub repositories.

## 1. Use the Cursor Desktop Application

The best way to use Cursor for general questions is via the installed desktop application (VS Code fork), not the web browser.

1.  **Download & Install**: If you haven't already, download the Cursor app for Mac.
2.  **Open a Local "Scratchpad"**:
    *   Create a folder on your Mac called `Cursor_Playground` or `Scratchpad`.
    *   Open this folder in Cursor (`File > Open Folder...`).
    *   **Do not initialize Git** in this folder.
    *   This gives you a sandbox where the AI can write code or files if asked, but nothing is ever pushed to GitHub unless you explicitly set that up.

## 2. Use the "Chat" Feature (Cmd + L)

For general questions ("How does X work?", "Explain this concept"), use the **Chat** interface.

*   **Shortcut**: `Cmd + L` (Mac)
*   **Behavior**: This is a conversational interface. It does **not** create files, branches, or commits automatically. It just answers your questions.
*   **Model Selection**: You can click the model dropdown in the chat window to select **Gemini 3 Pro** (or "Google" models) if available in your plan/settings.

## 3. Use "Composer" for Multi-file Ideas (Cmd + I)

If you want the AI to write code or longer documents but still want control:

*   **Shortcut**: `Cmd + I` (Mac)
*   **Behavior**: Composer can generate code across multiple files.
*   **Control**: It shows you the proposed changes in a "diff" view. You have to click "Accept" or "Save" to actually write the files to your disk. It does **not** automatically create Git commits or branches.

## Summary of Differences

| Feature | Cursor Web Agent (Browser) | Cursor Desktop Chat (`Cmd+L`) |
| :--- | :--- | :--- |
| **Primary Goal** | Complete coding tasks & create PRs | Answer questions & explain code |
| **Git Actions** | Automatic (Branch + Commit) | None (unless you run terminal commands) |
| **Persistence** | Permanent (Repo History) | Ephemeral (Chat History) |
| **Best For** | "Fix this bug", "Add this feature" | "How do I...?", "What is...?" |

## Conclusion

Stop using the saved Chrome App shortcut for general questions. Instead, keep the **Cursor Desktop App** open. It gives you the same AI power (Gemini 3 Pro) with zero Git overhead.
