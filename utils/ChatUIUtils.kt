package com.pauldevelopai.mediamap3.utils

import android.widget.TextView // If using TextView in Android
import androidx.recyclerview.widget.RecyclerView // If using RecyclerView
import com.pauldevelopai.mediamap3.models.ChatMessage
import com.pauldevelopai.mediamap3.adapters.ChatAdapter

// Example for updating a TextView
fun displayAiMessageInTextView(textView: TextView, message: String) {
    textView.text = message
}

// Example for adding a message to a RecyclerView (Adapt this to your specific RecyclerView adapter)
fun addAiMessageToRecyclerView(recyclerView: RecyclerView, adapter: ChatAdapter, message: String) {
    val aiMessage = ChatMessage(content = message, isUser = false)
    adapter.addMessage(aiMessage)
    recyclerView.scrollToPosition(adapter.itemCount - 1)
}

object ChatUIUtils {

    fun addAiMessageToRecyclerView(
        recyclerView: RecyclerView,
        adapter: ChatAdapter,
        message: String
    ) {
        val aiMessage = ChatMessage(content = message, isUser = false)
        adapter.addMessage(aiMessage)
        recyclerView.scrollToPosition(adapter.itemCount - 1)
    }
}