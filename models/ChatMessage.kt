package com.pauldevelopai.mediamap3.models

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "chat_messages")
data class ChatMessage(
    @PrimaryKey val id: String,
    val senderId: String,
    val recipientId: String,
    val messageText: String,
    val timestamp: Long,
    val isUserMessage: Boolean
)