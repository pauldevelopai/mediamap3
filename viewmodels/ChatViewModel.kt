import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class ChatViewModel { // Or wherever your UI logic resides

    private val chatService = ChatService() // Initialize the ChatService

    fun sendMessageToAi(message: String, displayMessage: (String) -> Unit) {
        CoroutineScope(Dispatchers.Main).launch {
            val aiResponse = chatService.sendMessage(message)
            displayMessage(aiResponse) // Callback to display the AI's response in the UI
        }
    }
}