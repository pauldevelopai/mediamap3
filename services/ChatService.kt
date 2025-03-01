package com.pauldevelopai.mediamap3.services

import io.ktor.client.*
import io.ktor.client.engine.cio.*
import io.ktor.client.plugins.contentnegotiation.*
import io.ktor.client.request.*
import io.ktor.client.statement.*
import io.ktor.http.*
import io.ktor.serialization.kotlinx.json.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.Json

class ChatService {

    private val apiKey = "YOUR_API_KEY" // Replace with your actual API key
    private val apiUrl = "https://api.example.com/chat" // Replace with the actual API endpoint
    private val client = HttpClient(CIO) {
        install(ContentNegotiation) {
            json(Json {
                ignoreUnknownKeys = true
                isLenient = true
            })
        }
    }

    suspend fun sendMessage(message: String): String {
        return withContext(Dispatchers.IO) {
            try {
                val response: HttpResponse = client.post(apiUrl) {
                    contentType(ContentType.Application.Json)
                    header("Authorization", "Bearer $apiKey")
                    setBody(mapOf("message" to message))
                }

                if (response.status.isSuccess()) {
                    response.bodyAsText()
                } else {
                    "Error: ${response.status.description}"
                }
            } catch (e: Exception) {
                "Error: ${e.message}"
            }
        }
    }
}