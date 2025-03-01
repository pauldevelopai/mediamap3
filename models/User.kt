package com.pauldevelopai.mediamap3.models

data class User(
    val id: String,
    val username: String,
    val email: String,
    val registrationDate: Long,
    val lastLogin: Long? = null,
    val isAdmin: Boolean = false
)