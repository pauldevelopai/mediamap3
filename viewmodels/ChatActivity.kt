import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.Observer
import com.pauldevelopai.mediamap3.utils.ChatUIUtils
import kotlinx.android.synthetic.main.activity_chat.*

class ChatActivity : AppCompatActivity() {

    private val chatViewModel: ChatViewModel by viewModels()
    private lateinit var mediaProjectionManager: MediaProjectionManager
    private lateinit var screenCaptureResultLauncher: ActivityResultLauncher<Intent>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_chat)

        mediaProjectionManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager

        screenCaptureResultLauncher = registerForActivityResult(
            ActivityResultContracts.StartActivityForResult()
        ) { result ->
            if (result.resultCode == RESULT_OK) {
                val intent: Intent? = result.data
                processScreenCaptureData(intent)
            } else {
                // User denied screen capture permission
            }
        }

        chatViewModel.aiResponse.observe(this, Observer { response ->
            displayAiMessageInTextView(response)
        })

        sendButton.setOnClickListener {
            onSendButtonClicked()
        }

        // Example: Add a button to start screen capture
        screenCaptureButton.setOnClickListener {
            startScreenCapture()
        }
    }

    private fun onSendButtonClicked() {
        val userMessage = messageInput.text.toString()
        if (userMessage.isNotBlank()) {
            chatViewModel.sendMessageToAi(userMessage)
            messageInput.text.clear()
        }
    }

    private fun displayAiMessageInTextView(message: String) {
        // Update your UI with the AI's response
        //ChatUIUtils.addAiMessageToRecyclerView(recyclerView, chatAdapter, message)
    }

    // function to start screen capture
    private fun startScreenCapture() {
        val captureIntent = mediaProjectionManager.createScreenCaptureIntent()
        screenCaptureResultLauncher.launch(captureIntent)
    }
    // function to process screen capture data
    private fun processScreenCaptureData(intent: Intent?) {
        // TODO: Implement logic to process the screen capture data (intent)
        // and send it to the Google AI Studio API.
    }
}