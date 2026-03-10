# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""AgentExecutor for STIRR Content Agent — bridges A2A protocol to our agent."""

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Task, TaskState, UnsupportedOperationError
from a2a.utils import new_agent_parts_message, new_agent_text_message, new_task
from a2a.utils.errors import ServerError
from a2ui.a2a import try_activate_a2ui_extension

logger = logging.getLogger(__name__)


class StirrContentAgentExecutor(AgentExecutor):
    """STIRR Content AgentExecutor."""

    def __init__(self, ui_agent, text_agent):
        self.ui_agent = ui_agent
        self.text_agent = text_agent

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        use_ui = try_activate_a2ui_extension(context)
        agent = self.ui_agent if use_ui else self.text_agent
        logger.info(f"Using {'UI' if use_ui else 'text'} agent")

        query = context.get_user_input()
        logger.info(f"Query: {query[:100]}...")

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        async for item in agent.stream(query, task.context_id):
            if not item["is_task_complete"]:
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(item["updates"], task.context_id, task.id),
                )
                continue

            await updater.update_status(
                TaskState.completed,
                new_agent_parts_message(item["parts"], task.context_id, task.id),
                final=True,
            )
            break

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
