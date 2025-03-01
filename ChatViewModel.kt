import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch

class ChatViewModel(private val chatService: ChatService) : ViewModel() {

    fun sendMessageToAi(message: String, displayMessage: (String) -> Unit) {
        viewModelScope.launch {
            try {
                val response = chatService.sendMessage(message)
                displayMessage(response)
            } catch (e: Exception) {
                displayMessage("Error: ${e.message}")
            }
        }
    }
} 