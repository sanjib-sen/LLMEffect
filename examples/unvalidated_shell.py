# In spirit of OpenAI local_shell tool calls. Expect LLM010.
import subprocess
import openai


def run_command(task):
    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "developer", "content": "Return a shell command."},
                  {"role": "user", "content": task}],
    )
    cmd = resp.choices[0].message.content
    subprocess.run(cmd, shell=True)
